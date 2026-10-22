import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { fmtInt, shortId } from "./lib/format";
import { deltaView, fmtValue, shortType } from "./lib/policyFormat";

describe("string helpers tolerate NULL columns from real data", () => {
  it("shortType never throws and keeps the provider-less tail", () => {
    expect(shortType(undefined)).toBe("(unknown type)");
    expect(shortType(null)).toBe("(unknown type)");
    expect(shortType("")).toBe("(unknown type)");
    expect(shortType("microsoft.compute/virtualmachines")).toBe("virtualmachines");
    expect(shortType("microsoft.sql/servers/databases")).toBe("servers/databases");
    expect(shortType("nodelimiter")).toBe("nodelimiter");
  });

  it("shortId and fmtInt tolerate missing values", () => {
    expect(shortId(undefined)).toBe("—");
    expect(shortId("abcdefghijklmnop")).toBe("abcdefgh…mnop");
    expect(fmtInt(undefined)).toBe("—");
    expect(fmtInt(null)).toBe("—");
    expect(fmtInt(1234)).toBe("1,234");
  });

  it("KPI helpers tolerate undefined value/delta", () => {
    const k = { id: "x", label: "x", unit: "count", goodDirection: "down" } as never;
    expect(fmtValue(k)).toBe("n/a");
    expect(deltaView(k).tone).toBe("none");
  });
});

describe("ErrorBoundary diagnostics", () => {
  it("shows the route and the component stack", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Bomb(): never {
      throw new Error("Cannot read properties of undefined (reading 'split')");
    }
    render(
      <ErrorBoundary route="/overview?x=1">
        <Bomb />
      </ErrorBoundary>,
    );
    const detail = screen.getByRole("alert").querySelector("pre")?.textContent ?? "";
    expect(detail).toContain("reading 'split'");
    expect(detail).toContain("Route: /overview?x=1");
    expect(detail).toContain("Components:");
    expect(detail).toContain("Bomb");
    spy.mockRestore();
  });
});
