import type { CategorySource, ComplianceState, EvidenceQuality, MetricFamily } from "../api/types";

export const FAMILY_LABEL: Record<MetricFamily, string> = {
  AzureWindowsBaseline: "Windows baseline (Azure)",
  CISWindowsSecurityBaseline: "CIS Windows security baseline",
};

export const FAMILIES: MetricFamily[] = ["AzureWindowsBaseline", "CISWindowsSecurityBaseline"];

export type Tone = "good" | "warn" | "bad" | "nodata" | "stale";

/** Presentation thresholds only; they are not a compliance or certification claim. */
export function toneFor(percent: number | null, stale: boolean): Tone {
  if (percent === null) return "nodata";
  if (stale) return "stale";
  if (percent >= 90) return "good";
  if (percent >= 70) return "warn";
  return "bad";
}

export function formatPercent(percent: number | null): string {
  return percent === null ? "No data" : `${percent.toFixed(1)}%`;
}

/** Provenance label for a check category; derived categories are app heuristics, not benchmark mappings. */
export function categoryProvenance(
  source: CategorySource | undefined,
  version: number | null | undefined,
): { label: string; hint: string } {
  switch (source) {
    case "derived":
      return {
        label: `Derived category (app rules v${version ?? "?"})`,
        hint: "Grouped by app heuristic rules over the check name. Not provided by the source report and not a benchmark or certification mapping.",
      };
    case "override":
      return {
        label: "Category override (repo config)",
        hint: "Mapped by an operator-managed override. Not provided by the source report.",
      };
    case "unmapped":
      return {
        label: "Unmapped (no rule matched)",
        hint: "No category in the source report and no app rule matched this check.",
      };
    case "mixed":
      return {
        label: "Mixed provenance",
        hint: "Checks in this category come from different category sources.",
      };
    default:
      return {
        label: "Source category",
        hint: "Category provided by the source report.",
      };
  }
}

export const TONE_TEXT: Record<Tone, string> = {
  good: "Meets target",
  warn: "Needs attention",
  bad: "Below target",
  nodata: "No data",
  stale: "Stale data",
};

export const QUALITY_LABEL: Record<EvidenceQuality, string> = {
  Fresh: "Fresh evidence",
  Stale: "Stale evidence",
  UnknownAge: "Unknown report age",
  NoReport: "No report",
  MissingAssignment: "No assignment",
  UnknownApplicability: "Applicability unknown",
};

export function qualityTone(q: EvidenceQuality, state: ComplianceState | null): Tone {
  if (q !== "Fresh") return q === "Stale" || q === "UnknownAge" ? "stale" : "nodata";
  return state === "Compliant" ? "good" : "bad";
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "unknown"
    : d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function shortId(id: string): string {
  return id.length > 13 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}
