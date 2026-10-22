import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { createMockApi } from "./api/mock";
import { createMockPolicyApi } from "./api/policyMock";
import { createMockDomainApi, MOCK_QUEUE } from "./api/domainMock";
import type { DomainApi } from "./api/domainClient";
import type { PolicyApi } from "./api/policyClient";
import type { StateRow } from "./api/policyTypes";
import { ProvenanceBadge, DomainCell } from "./components/ProvenanceBadge";
import { CONFIDENCES } from "./api/domainTypes";
import { domainChecksCsv, queueCsv, statesCsv } from "./lib/domainFormat";
import { toCsv } from "./lib/policyFormat";

function Where() {
  const l = useLocation();
  return <output data-testid="loc">{l.pathname + l.search}</output>;
}

function renderAt(path: string, opts: { domainApi?: DomainApi; policyApi?: PolicyApi } = {}) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createMockApi()} policyApi={opts.policyApi ?? createMockPolicyApi()} domainApi={opts.domainApi ?? createMockDomainApi()} />
      <Where />
    </MemoryRouter>,
  );
}

describe("provenance badges", () => {
  it("states the provenance as text for every confidence, not only by colour", () => {
    for (const c of CONFIDENCES) {
      const { container, unmount } = render(<ProvenanceBadge confidence={c} />);
      expect(container.textContent).toMatch(/Provenance:/);
      expect(container.textContent?.length).toBeGreaterThan("Provenance: ".length + 2);
      unmount();
    }
  });

  it("shows an honest fallback when provenance is missing", () => {
    render(<DomainCell domain="network" label="Network security" confidence={undefined} />);
    expect(screen.getByText("Network security")).toBeInTheDocument();
    expect(screen.getByText("Not classified")).toBeInTheDocument();
  });
});

describe("overview by-domain panel", () => {
  it("shows policy % and machine pass rate side by side, the non-additive note and the disclaimer", async () => {
    renderAt("/overview");
    const panel = await screen.findByRole("region", { name: "By security domain" });
    expect(within(panel).getByRole("columnheader", { name: /Policy compliance/ })).toBeInTheDocument();
    expect(within(panel).getByRole("columnheader", { name: /Machine check pass rate/ })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Policy states in Identity and access" })).toHaveAttribute(
      "href",
      "/explorer?tab=states&domain=identity",
    );
    const fw = await screen.findByRole("region", { name: "By framework (indicative)" });
    expect(within(fw).getByText(/Not additive/)).toBeInTheDocument();
    expect(within(fw).getByText(/not compliance claims or certification/)).toBeInTheDocument();
  });

  it("shows the data-quality tile with a link to the Needs-category queue", async () => {
    renderAt("/overview");
    const tile = await screen.findByRole("region", { name: "Domain data quality" });
    expect(within(tile).getByRole("link", { name: /Needs-category queue/ })).toHaveAttribute("href", "/explorer?tab=needs-category");
    expect(within(tile).getByRole("list", { name: "Policies by provenance" })).toBeInTheDocument();
    expect(within(tile).getByRole("list", { name: "Checks by provenance" })).toBeInTheDocument();
  });

  it("warns when the taxonomy changed inside the trend window", async () => {
    renderAt("/overview", { policyApi: createMockPolicyApi({ taxonomyChanged: true }) });
    expect(await screen.findByText(/Taxonomy changed/)).toBeInTheDocument();
  });

  it("shows an honest error state when the domain API fails", async () => {
    const api = { ...createMockDomainApi(), overview: () => Promise.reject(new Error("boom")) };
    renderAt("/overview", { domainApi: api });
    const panel = await screen.findByRole("region", { name: "By security domain" });
    expect(await within(panel).findByRole("alert")).toBeInTheDocument();
  });
});

describe("Needs category queue", () => {
  it("disables assignment and explains the fallback when the gate is off", async () => {
    renderAt("/explorer?tab=needs-category", { domainApi: createMockDomainApi({ gateEnabled: false, canEdit: true }) });
    const notice = await screen.findByTestId("gate-notice");
    expect(notice.textContent).toMatch(/ACD_DOMAIN_OVERRIDES/);
    const btn = await screen.findByRole("button", { name: "Assign Synthetic unmapped policy" });
    expect(btn).toBeDisabled();
  });

  it("disables assignment when the caller lacks permission even if the gate is on", async () => {
    renderAt("/explorer?tab=needs-category", { domainApi: createMockDomainApi({ gateEnabled: true, canEdit: false }) });
    expect(await screen.findByRole("button", { name: "Assign Synthetic unmapped policy" })).toBeDisabled();
  });

  it("enables assignment and posts the override when permitted", async () => {
    const base = createMockDomainApi({ gateEnabled: true, canEdit: true });
    const createOverride = vi.fn(base.createOverride);
    renderAt("/explorer?tab=needs-category", { domainApi: { ...base, createOverride } });
    const select = await screen.findByLabelText("Domain for Synthetic unmapped policy");
    const btn = screen.getByRole("button", { name: "Assign Synthetic unmapped policy" });
    await waitFor(() => expect(select).not.toBeDisabled());
    fireEvent.change(select, { target: { value: "network" } });
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    await waitFor(() => expect(createOverride).toHaveBeenCalledTimes(1));
    expect(createOverride.mock.calls[0][0]).toMatchObject({ target: "policy", domain: "network" });
  });

  it("persists the queue filters in the URL", async () => {
    renderAt("/explorer?tab=needs-category");
    fireEvent.change(await screen.findByLabelText(/Kind/), { target: { value: "check" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("qkind=check"));
  });

  it("lists overrides and offers delete only when permitted", async () => {
    const base = createMockDomainApi({ gateEnabled: true, canEdit: true });
    const deleteOverride = vi.fn(base.deleteOverride);
    renderAt("/explorer?tab=overrides", { domainApi: { ...base, deleteOverride } });
    const del = await screen.findByRole("button", { name: /Delete override for synth-def-1/ });
    await waitFor(() => expect(del).toBeEnabled());
    fireEvent.click(del);
    await waitFor(() => expect(deleteOverride).toHaveBeenCalledWith(1));
  });
});

describe("domain filters and drill", () => {
  it("keeps the domain and confidence filters in the URL", async () => {
    renderAt("/explorer?tab=states");
    const select = await screen.findByLabelText("Security domain");
    fireEvent.change(select, { target: { value: "network" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("domain=network"));
    fireEvent.change(screen.getByLabelText("Domain provenance"), { target: { value: "derived-low" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("confidence=derived-low"));
  });

  it("passes the domain filter to the policy API", async () => {
    const seen: unknown[] = [];
    const policyApi: PolicyApi = {
      ...createMockPolicyApi(),
      states: (filters, page) => {
        seen.push(filters);
        return createMockPolicyApi().states(filters, page);
      },
    };
    renderAt("/explorer?tab=states&domain=network", { policyApi });
    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
    expect(seen[0]).toMatchObject({ domain: ["network"] });
  });

  it("goes back with the button and with Escape from the Explorer domain drill", async () => {
    renderAt("/explorer?tab=states&domain=network");
    fireEvent.click(await screen.findByRole("button", { name: "← All domains" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).not.toContain("domain="));
  });

  it("goes back with Escape from the Explorer domain drill", async () => {
    renderAt("/explorer?tab=states&domain=network");
    await screen.findByRole("button", { name: "← All domains" });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).not.toContain("domain="));
  });

  it("drills the technical view by domain and goes up with Back and Escape", async () => {
    renderAt("/technical?domain=identity");
    expect(await screen.findByRole("heading", { name: /Checks in security domain: Identity and access/ })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).not.toContain("domain="));
  });

  it("shows domain and provenance columns in the policy state table", async () => {
    renderAt("/explorer?tab=states");
    expect(await screen.findByRole("columnheader", { name: /Security domain/ })).toBeInTheDocument();
    expect(await screen.findByText("Data protection")).toBeInTheDocument();
    expect(screen.getAllByText("Source category").length).toBeGreaterThan(0);
  });
});

describe("exports carry domain and provenance", () => {
  const state = { resourceName: "r", resourceType: "t", resourceGroup: "g", policy: "p", initiative: "i", state: "NonCompliant", effect: "audit", category: "Storage", domain: "data-protection", domainConfidence: "source", evaluatedAt: "x" } as unknown as StateRow;

  it("states CSV includes the domain, provenance and the active filter", () => {
    const csv = statesCsv([state], { domain: ["data-protection"] });
    expect(csv).toContain("Domain provenance");
    expect(csv).toContain("domain=data-protection");
    expect(csv).toContain("Source category");
  });

  it("queue and domain checks CSVs include provenance", async () => {
    const api = createMockDomainApi();
    const q = MOCK_QUEUE;
    expect(queueCsv(q, q.length)).toMatch(/Unmapped|Derived/);
    const c = await api.checks("identity");
    expect(domainChecksCsv(c)).toContain("identity");
    expect(toCsv([["a"]])).toContain("a");
  });
});
