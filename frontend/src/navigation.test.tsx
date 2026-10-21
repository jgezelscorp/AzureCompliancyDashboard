import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { MetricsApi } from "./api/client";
import { createMockApi } from "./api/mock";

function renderAt(path: string, api: MetricsApi) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={api} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
});
afterEach(() => vi.restoreAllMocks());

async function firstCategory(): Promise<string> {
  const table = await screen.findByRole("table", {
    name: "Check results by category",
  });
  const btn = within(table).getAllByRole("button")[0];
  const name = btn.textContent ?? "";
  fireEvent.click(btn);
  return name;
}

describe("export section controls", () => {
  it("collapses, remembers the state and restores it", async () => {
    const api = createMockApi();
    const first = renderAt("/technical", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Collapse export section" }),
    );
    const toggle = screen.getByRole("button", {
      name: "Expand export section",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("acd.export.collapsed")).toBe("1");
    first.unmount();
    renderAt("/technical", api);
    expect(
      await screen.findByRole("button", { name: "Expand export section" }),
    ).toBeVisible();
  });

  it("hides the whole section and brings it back", async () => {
    renderAt("/technical", createMockApi());
    fireEvent.click(
      await screen.findByRole("button", { name: "Hide export section" }),
    );
    expect(
      screen.queryByRole("button", { name: "Export checks CSV" }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Show export section" }),
    );
    expect(
      await screen.findByRole("button", { name: "Export checks CSV" }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("acd.export.hidden")).toBeNull();
  });

  it("removes a single row and clears finished rows client-side", async () => {
    const api = createMockApi();
    renderAt("/technical", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Export checks CSV" }),
    );
    await screen.findByText("Ready");
    fireEvent.click(
      screen.getByRole("button", { name: /^Remove .* from list$/ }),
    );
    expect(screen.queryByText("Ready")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Clear finished and expired" }),
    ).toBeNull();
  });
});

describe("drill-down navigation", () => {
  it("heading and listed checks match the clicked category and Back returns up", async () => {
    const api = createMockApi();
    const spy = vi.spyOn(api, "checks");
    renderAt("/technical", api);
    const name = await firstCategory();
    expect(
      await screen.findByRole("heading", { name: `Checks in ${name}` }),
    ).toBeInTheDocument();
    expect(spy.mock.calls[0][1]).toBe(name);
    fireEvent.click(screen.getByRole("button", { name: "← All categories" }));
    expect(
      await screen.findByRole("table", { name: "Check results by category" }),
    ).toBeVisible();
  });

  it("Escape and the breadcrumb go up one level", async () => {
    renderAt("/technical", createMockApi());
    const name = await firstCategory();
    await screen.findByRole("heading", { name: `Checks in ${name}` });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      await screen.findByRole("table", { name: "Check results by category" }),
    ).toBeVisible();
    await firstCategory();
    const nav = screen.getByRole("navigation", { name: "Drill-down path" });
    fireEvent.click(
      within(nav).getByRole("button", { name: "Windows baseline (Azure)" }),
    );
    expect(
      await screen.findByRole("table", { name: "Check results by category" }),
    ).toBeVisible();
  });

  it("goes from the check level back to the category's checks", async () => {
    renderAt("/technical", createMockApi());
    const name = await firstCategory();
    const list = await screen.findByRole("table", {
      name: "Checks with machine counts",
    });
    fireEvent.click(within(list).getAllByRole("button")[0]);
    await screen.findByRole("table", {
      name: "Machines and their result for this check",
    });
    fireEvent.click(
      screen.getByRole("button", { name: `← Checks in ${name}` }),
    );
    expect(
      await screen.findByRole("heading", { name: `Checks in ${name}` }),
    ).toBeInTheDocument();
  });

  it("refuses to list checks when the server answers for another category", async () => {
    const api = createMockApi();
    const real = api.checks;
    api.checks = async (...args) => ({
      ...(await real(...args)),
      category: "Other category",
    });
    renderAt("/technical", api);
    await firstCategory();
    expect(
      await screen.findByText(/different category than the one selected/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: "Checks with machine counts" }),
    ).toBeNull();
  });
});
