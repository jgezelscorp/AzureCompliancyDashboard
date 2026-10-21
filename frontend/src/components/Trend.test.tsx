import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { Trend } from "./Trend";
import { errorMessage } from "./common";

describe("Trend", () => {
  it("draws a marker and a sample note for a single point", () => {
    const { container } = render(
      <Trend series={{ label: "Check pass rate (%)", values: [{ at: "2026-10-21T18:12:00Z", value: 29.2 }] }} />,
    );
    expect(container.querySelectorAll("circle.trend-point")).toHaveLength(1);
    expect(screen.getByText(/Only 1 sample so far/)).toBeTruthy();
  });

  it("draws a line and markers for several points and skips null gaps", () => {
    const { container } = render(
      <Trend
        series={{
          label: "Check pass rate (%)",
          values: [
            { at: "2026-10-21T10:00:00Z", value: null },
            { at: "2026-10-21T14:00:00Z", value: 20 },
            { at: "2026-10-21T18:00:00Z", value: 30 },
            { at: "2026-10-22T00:00:00Z", value: 40 },
          ],
        }}
      />,
    );
    expect(container.querySelectorAll("circle.trend-point")).toHaveLength(3);
    expect(container.querySelector("path")?.getAttribute("d")).toMatch(/^M.*L.*L/);
    expect(screen.queryByText(/samples so far/)).toBeNull();
  });
});

describe("errorMessage", () => {
  it("names the failure class", () => {
    expect(errorMessage(new ApiError(0, "x"))).toMatch(/Network error/);
    expect(errorMessage(new ApiError(-1, "x"))).toMatch(/incomplete/);
    expect(errorMessage(new ApiError(404, "x"))).toMatch(/rejected \(404\)/);
    expect(errorMessage(new ApiError(500, "x"))).toMatch(/Server error \(500\)/);
  });
});
