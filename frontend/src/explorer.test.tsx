import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import { createMockApi } from "./api/mock";
import { createMockPolicyApi } from "./api/policyMock";
import type { PolicyApi } from "./api/policyClient";

function Where() {
  const l = useLocation();
  return <output data-testid="loc">{l.pathname + l.search}</output>;
}

function renderAt(path: string, policyApi: PolicyApi = createMockPolicyApi()) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createMockApi()} policyApi={policyApi} />
      <Where />
    </MemoryRouter>,
  );
}

describe("technical explorer", () => {
  it("reads tab and filters from the URL and passes them to the API", async () => {
    const seen: unknown[] = [];
    const api: PolicyApi = {
      ...createMockPolicyApi(),
      states: (filters, page) => {
        seen.push({ filters, page });
        return createMockPolicyApi().states(filters, page);
      },
    };
    renderAt("/explorer?tab=states&state=NonCompliant&rg=rg-synthetic&sort=policy&desc=false", api);
    expect(await screen.findByRole("table", { name: "Policy states" })).toBeInTheDocument();
    expect(seen[0]).toMatchObject({
      filters: { state: ["NonCompliant"], rg: ["rg-synthetic"] },
      page: { sort: "policy", desc: false, offset: 0 },
    });
  });

  it("shows grain-consistent counts above the table", async () => {
    renderAt("/explorer?tab=states");
    expect(await screen.findByText(/10 evaluations match/)).toBeInTheDocument();
  });

  it("sorting and tab changes are written to the URL", async () => {
    renderAt("/explorer?tab=states");
    fireEvent.click(await screen.findByRole("button", { name: /^Policy/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("sort=policy"));
    fireEvent.click(screen.getByRole("tab", { name: "Resources" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("tab=resources"));
    expect(screen.getByTestId("loc").textContent).not.toContain("sort=");
  });

  it("removing a filter chip updates the URL", async () => {
    renderAt("/explorer?tab=states&state=NonCompliant");
    fireEvent.click(await screen.findByRole("button", { name: /Remove filter state NonCompliant/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).not.toContain("state="));
  });

  it("links a row to the resource detail page and renders its policy states", async () => {
    renderAt("/explorer?tab=states");
    const row = await screen.findByRole("table", { name: "Policy states" });
    fireEvent.click(within(row).getByRole("link", { name: "stsynth" }));
    expect(await screen.findByRole("heading", { name: "stsynth" })).toBeInTheDocument();
    expect(await screen.findByText("Policy states for this resource")).toBeInTheDocument();
  });

  it("renders the machine detail page with honest empty sections", async () => {
    renderAt("/machine?id=m1");
    expect(await screen.findByRole("heading", { name: "vm-synthetic" })).toBeInTheDocument();
    expect(screen.getByText("0 samples so far.")).toBeInTheDocument();
    expect(screen.getByText(/No Azure Policy evaluations for this machine/)).toBeInTheDocument();
  });

  it("paginates with Previous/Next disabled at the bounds", async () => {
    renderAt("/explorer?tab=states");
    expect(await screen.findByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});
