import { describe, expect, it } from "vitest";
import { categoryProvenance, formatPercent, qualityTone, shortId, toneFor } from "./format";

describe("categoryProvenance", () => {
  it("labels derived categories with the rules version and never as source-backed", () => {
    const p = categoryProvenance("derived", 3);
    expect(p.label).toBe("Derived category (app rules v3)");
    expect(p.hint).toMatch(/not a benchmark/i);
  });
  it("labels override, unmapped, mixed and source", () => {
    expect(categoryProvenance("override", 1).label).toMatch(/override/i);
    expect(categoryProvenance("unmapped", 1).label).toMatch(/unmapped/i);
    expect(categoryProvenance("mixed", 1).label).toMatch(/mixed/i);
    expect(categoryProvenance("source", 1).label).toBe("Source category");
    expect(categoryProvenance(undefined, undefined).label).toBe("Source category");
  });
});

describe("toneFor", () => {
  it("never reports no-data or stale as good", () => {
    expect(toneFor(null, false)).toBe("nodata");
    expect(toneFor(100, true)).toBe("stale");
  });
  it("applies thresholds", () => {
    expect(toneFor(95, false)).toBe("good");
    expect(toneFor(75, false)).toBe("warn");
    expect(toneFor(10, false)).toBe("bad");
  });
});

describe("helpers", () => {
  it("formats percent", () => {
    expect(formatPercent(null)).toBe("No data");
    expect(formatPercent(50)).toBe("50.0%");
  });
  it("maps evidence quality", () => {
    expect(qualityTone("Stale", "Compliant")).toBe("stale");
    expect(qualityTone("NoReport", null)).toBe("nodata");
    expect(qualityTone("Fresh", "Compliant")).toBe("good");
    expect(qualityTone("Fresh", "NonCompliant")).toBe("bad");
  });
  it("shortens ids", () => {
    expect(shortId("00000000-0000-0000-0000-000000000000")).toBe("00000000…0000");
  });
});
