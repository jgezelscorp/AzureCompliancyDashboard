import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";

const files = import.meta.glob("./test/server-shapes/*.json", { eager: true, import: "default" }) as Record<string, unknown>;
const shape = (name: string): unknown => files[`./test/server-shapes/${name}.json`];

/** Maps request paths to JSON that was produced by the real FastAPI app on synthetic rows. */
function route(url: URL): unknown {
  const p = url.pathname;
  const q = url.searchParams;
  if (p === "/api/v1/policy/breakdown") return shape(q.get("by") === "initiative" ? "policy-breakdown-init" : "policy-breakdown");
  const direct: Record<string, string> = {
    "/api/v1/policy/overview": "policy-overview",
    "/api/v1/policy/top-policies": "policy-top",
    "/api/v1/policy/states": "policy-states",
    "/api/v1/policy/resources": "policy-resources",
    "/api/v1/policy/exemptions": "policy-exemptions",
    "/api/v1/policy/trend": "policy-trend",
    "/api/v1/policy/filters": "policy-filters",
    "/api/v1/policy/quality": "policy-quality",
    "/api/v1/policy/machines/coverage": "policy-machines-coverage",
    "/api/v1/domains/taxonomy": "domains-taxonomy",
    "/api/v1/domains/overview": "domains-overview",
    "/api/v1/domains/frameworks": "domains-frameworks",
    "/api/v1/domains/provenance": "domains-provenance",
    "/api/v1/domains/queue": "domains-queue",
    "/api/v1/domains/overrides": "domains-overrides",
    "/api/v1/metrics/latest": "metrics-latest",
    "/api/v1/metrics/scopes": "metrics-scopes",
    "/api/v1/metrics/history": "metrics-history",
    "/api/v1/metrics/machines": "metrics-machines",
    "/api/v1/metrics/categories": "metrics-categories",
    "/api/v1/auth/capabilities": "auth-capabilities",
  };
  return direct[p] ? shape(direct[p]) : undefined;
}

const unmatched: string[] = [];

beforeEach(() => {
  unmatched.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const body = route(url);
      if (body === undefined) {
        unmatched.push(url.pathname);
        return new Response(JSON.stringify({ detail: "not found" }), { status: 404, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

const PAGES = [
  "/overview",
  "/explorer",
  "/explorer?tab=states",
  "/explorer?tab=policies",
  "/explorer?tab=resources",
  "/explorer?tab=machines",
  "/explorer?tab=needs-category",
  "/technical",
  "/ciso",
];

describe("real server response shapes never blank the screen", () => {
  for (const page of PAGES) {
    it(`renders ${page}`, async () => {
      const errors: unknown[] = [];
      const spy = vi.spyOn(console, "error").mockImplementation((...a) => {
        errors.push(a);
      });
      render(
        <MemoryRouter initialEntries={[page]}>
          <App skipAuth />
        </MemoryRouter>,
      );
      await waitFor(() => expect(screen.getByRole("main")).toBeInTheDocument());
      await new Promise((r) => setTimeout(r, 300));
      expect(screen.queryByText(/Something went wrong/i)).not.toBeInTheDocument();
      expect(screen.getByRole("main").textContent?.length ?? 0).toBeGreaterThan(20);
      const crash = errors.find((e) => String((e as unknown[])[0]).includes("The above error occurred") || String((e as unknown[])[0]).includes("Uncaught"));
      expect(crash, JSON.stringify(errors.slice(0, 2)).slice(0, 600)).toBeUndefined();
      spy.mockRestore();
    });
  }

  it("machine KPIs sent as { page: 'machines' } link to the machines tab", async () => {
    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <App skipAuth />
      </MemoryRouter>,
    );
    const link = await screen.findAllByRole("link", { name: "Show the rows" });
    expect(link.some((a) => a.getAttribute("href") === "/explorer?tab=machines")).toBe(true);
  });
});

describe("ErrorBoundary", () => {
  it("shows a readable error with Back and Reload instead of unmounting the app", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Bomb(): never {
      throw new Error("boom");
    }
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/Something went wrong/);
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    spy.mockRestore();
  });
});
