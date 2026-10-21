import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import type { MetricsApi } from "./api/client";
import { createMockApi } from "./api/mock";
import type { FamilyMetrics, LatestMetrics } from "./api/types";

function renderAt(path: string, api: MetricsApi = createMockApi()) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={api} />
    </MemoryRouter>,
  );
}

async function assertNoA11yViolations(container: HTMLElement) {
  // jsdom has no layout engine, so colour contrast cannot be evaluated here.
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`),
  ).toEqual([]);
}

describe("Technical view drill-down", () => {
  it("drills from category to check to machines and back via breadcrumbs", async () => {
    renderAt("/technical?family=AzureWindowsBaseline");
    const categories = await screen.findByRole("table", { name: "Check results by category" });
    fireEvent.click(within(categories).getByRole("button", { name: "Audit Policy" }));

    const checks = await screen.findByRole("table", { name: "Checks with machine counts" });
    expect(screen.getByRole("heading", { name: "Checks in Audit Policy" })).toBeInTheDocument();
    fireEvent.click(within(checks).getByRole("button", { name: "Audit Logon events" }));

    const machines = await screen.findByRole("table", {
      name: "Machines and their result for this check",
    });
    expect(within(machines).getByText("demo-vm-01")).toBeInTheDocument();
    expect(within(machines).getByText("Failing")).toBeInTheDocument();
    expect(within(machines).getAllByText("Passing").length).toBeGreaterThan(0);
    const crumbs = screen.getByRole("navigation", { name: "Drill-down path" });
    expect(within(crumbs).getByText("[Audit Policy]Audit Logon")).toHaveAttribute(
      "aria-current",
      "page",
    );

    fireEvent.click(within(crumbs).getByRole("button", { name: "Audit Policy" }));
    expect(await screen.findByRole("table", { name: "Checks with machine counts" })).toBeVisible();
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Drill-down path" })).getByRole("button", {
        name: "Windows baseline (Azure)",
      }),
    );
    expect(await screen.findByRole("table", { name: "Check results by category" })).toBeVisible();
  });

  it("filters by scope and resets deeper selections when the baseline changes", async () => {
    renderAt("/technical?category=Audit%20Policy&family=AzureWindowsBaseline");
    await screen.findByRole("table", { name: "Checks with machine counts" });
    fireEvent.click(screen.getByRole("button", { name: /CIS/ }));
    await waitFor(() =>
      expect(screen.queryByRole("table", { name: "Checks with machine counts" })).toBeNull(),
    );
    expect(await screen.findByRole("table", { name: "Check results by category" })).toBeVisible();

    fireEvent.change(screen.getByLabelText(/Scope/), {
      target: { value: "00000000-0000-0000-0000-000000000001" },
    });
    const machines = await screen.findByRole("table", { name: "Machine evidence status" });
    await waitFor(() => expect(within(machines).queryByText("demo-vm-01")).toBeNull());
    expect(within(machines).getByText("demo-arc-01")).toBeInTheDocument();
  });

  it("never presents stale, missing or no-report machines as passing", async () => {
    renderAt("/technical?family=CISWindowsSecurityBaseline");
    const table = await screen.findByRole("table", { name: "Machine evidence status" });
    const rows = within(table).getAllByRole("row").slice(1);
    for (const row of rows) {
      const text = row.textContent ?? "";
      if (/Stale|No assignment|Missing|No report/i.test(text)) {
        expect(text).toMatch(/Not assessed/);
        expect(text).not.toMatch(/Compliant|Passing|Healthy/);
      }
    }
    expect(rows.some((r) => /Not assessed/.test(r.textContent ?? ""))).toBe(true);
  });
});

describe("honest evidence labels", () => {
  it("shows a stale-data alert and the no-certification disclosure", async () => {
    renderAt("/technical");
    expect(await screen.findByRole("alert")).toHaveTextContent(/older than 24 hours/i);
    expect(screen.getAllByText(/not a CIS, ISO, NIS2 or DORA certification/i).length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText(/missing or stale evidence is never green/i).length).toBeGreaterThan(
      0,
    );
  });

  it("flags CIS evidence as unverified and never claims certification", async () => {
    const { container } = renderAt("/technical?family=CISWindowsSecurityBaseline");
    await screen.findByText(/CIS evidence is not verified as live/i);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\bis (CIS[- ])?certified\b|\bcertified compliant\b|\bpassed certification\b/i);
  });

  it("shows no data as no data, not as 0% or 100%", async () => {
    const base = createMockApi();
    const empty: LatestMetrics = {
      snapshotAt: null,
      dataStale: false,
      freshnessHours: 24,
      families: [] as FamilyMetrics[],
      labels: ["No data is not compliance: missing or stale evidence is never green."],
      scope: { authorizedSubscriptions: 1, onboardedSubscriptions: 1, partial: false },
    };
    renderAt("/technical", { ...base, latest: () => Promise.resolve(empty) });
    expect(await screen.findByText(/No collection has completed yet/i)).toBeVisible();
    expect(screen.queryByText(/100\s?%/)).toBeNull();
  });
});

describe("accessibility (axe)", () => {
  it.each([
    ["Technical overview", "/technical?family=AzureWindowsBaseline"],
    ["Technical CIS", "/technical?family=CISWindowsSecurityBaseline"],
    ["Technical checks", "/technical?family=AzureWindowsBaseline&category=Audit%20Policy"],
    [
      "Technical machines",
      "/technical?family=AzureWindowsBaseline&category=Audit%20Policy&check=%5BAudit%20Policy%5DAudit%20Logon",
    ],
    ["CISO", "/ciso"],
  ])("%s has no detectable violations", async (_name, path) => {
    const { container } = renderAt(path);
    await waitFor(() => expect(screen.queryByText(/^Loading/i)).toBeNull());
    await waitFor(() => expect(container.querySelector("table, .notice")).not.toBeNull());
    await assertNoA11yViolations(container);
  });
});
