import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import { createMockApi } from "./api/mock";
import { ApiError } from "./api/client";
import { createMockPolicyApi } from "./api/policyMock";
import type { PolicyApi } from "./api/policyClient";
import { deltaView, drillSearch, filtersFromSearch, rowDrill, toCsv } from "./lib/policyFormat";
import { policyQuery } from "./api/policyClient";
import type { Kpi } from "./api/policyTypes";

function renderOverview(policyApi: PolicyApi = createMockPolicyApi()) {
  return render(
    <MemoryRouter initialEntries={["/overview"]}>
      <App api={createMockApi()} policyApi={policyApi} />
    </MemoryRouter>,
  );
}

const K = (p: Partial<Kpi>): Kpi => ({
  id: "x", label: "x", value: 1, unit: "percent", status: "ok", numerator: null, denominator: null,
  grain: "g", formula: "f", drill: null, goodDirection: "up", note: null, previous: null, delta: null,
  previousAt: null, sparkline: [], ...p,
});

describe("policy overview page", () => {
  it("shows KPIs with denominators, summary and honesty labels", async () => {
    renderOverview();
    expect(await screen.findByRole("heading", { name: "CISO overview" })).toBeInTheDocument();
    const tile = await screen.findByRole("article", { name: "Azure Policy compliance" });
    expect(within(tile).getByText("66.7 %")).toBeInTheDocument();
    expect(within(tile).getByText(/6 of 9/)).toBeInTheDocument();
    expect(screen.getAllByText(/3 samples so far/).length).toBeGreaterThan(0);
    expect(screen.getByText(/never combined/)).toBeInTheDocument();
  });

  it("shows no-data KPIs as n/a, never as zero or green", async () => {
    renderOverview();
    const tile = await screen.findByRole("article", { name: "High-impact failing policies" });
    expect(within(tile).getByText("n/a")).toBeInTheDocument();
    expect(within(tile).getByText(/No definition carries severity/)).toBeInTheDocument();
  });

  it("opens the calculation popover with formula and denominator", async () => {
    renderOverview();
    const tile = await screen.findByRole("article", { name: "Azure Policy compliance" });
    fireEvent.click(within(tile).getByRole("button", { name: /how is this calculated/i }));
    expect(within(tile).getByRole("region", { name: /calculated/i })).toHaveTextContent("Denominator");
  });

  it("links drill-through to the explorer with filters in the URL", async () => {
    renderOverview();
    const link = await screen.findByRole("link", { name: "Synthetic definition" });
    expect(link.getAttribute("href")).toContain("/explorer?tab=states");
    expect(link.getAttribute("href")).toContain("state=NonCompliant");
  });

  it("offers a tabular alternative for the trend chart", async () => {
    renderOverview();
    fireEvent.click(await screen.findByText("Show the numbers"));
    expect(await screen.findByRole("table", { name: /trend samples/i })).toBeInTheDocument();
  });

  it("reports a failing panel without hiding the rest", async () => {
    const api = { ...createMockPolicyApi(), quality: () => Promise.reject(new ApiError(500, "x")) };
    renderOverview(api);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Compliance trend" })).toBeInTheDocument();
  });

  it("explains 403 without leaking data", async () => {
    const api = { ...createMockPolicyApi(), overview: () => Promise.reject(new ApiError(403, "x")) };
    renderOverview(api);
    await waitFor(() => expect(screen.getAllByRole("alert")[0]).toHaveTextContent(/access denied/i));
  });
});

describe("policy helpers", () => {
  it("prints direction and meaning of deltas", () => {
    expect(deltaView(K({ delta: 2, previous: 50 }))).toMatchObject({ tone: "better" });
    expect(deltaView(K({ delta: 2, previous: 5, goodDirection: "down", unit: "count" }))).toMatchObject({ tone: "worse" });
    expect(deltaView(K({}))).toMatchObject({ tone: "none" });
  });

  it("builds exact drill filters and refuses inexact ones", () => {
    expect(rowDrill("resourceType", { key: "a/b", label: "a/b" })).toEqual({ rtype: ["a/b"] });
    expect(rowDrill("tag:owner", { key: "(untagged)", label: "(untagged)" })).toBeNull();
    expect(rowDrill("initiative", { key: "__standalone", label: "Standalone" })).toBeNull();
    expect(rowDrill("resourceGroup", { key: "s|rg1", label: "rg1" })).toEqual({ rg: ["rg1"] });
  });

  it("round-trips filters through the URL", () => {
    const s = drillSearch({ tab: "states", params: { state: ["NonCompliant"], sub: ["a", "b"] } });
    const q = new URLSearchParams(s);
    expect(q.get("tab")).toBe("states");
    expect(filtersFromSearch(q)).toEqual({ state: ["NonCompliant"], sub: ["a", "b"] });
    expect(policyQuery({ sub: ["a", "b"] }, { limit: 5 })).toBe("?sub=a&sub=b&limit=5");
  });

  it("neutralizes spreadsheet formulas in CSV", () => {
    expect(toCsv([["=1+1", 'a"b']])).toBe("'=1+1,\"a\"\"b\"\r\n");
  });
});
