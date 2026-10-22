import type { Drill, Filters, Kpi } from "../api/policyTypes";
import { FILTER_KEYS } from "../api/policyTypes";

export function fmtValue(k: Pick<Kpi, "value" | "unit">): string {
  if (k.value === null || k.value === undefined) return "n/a";
  return k.unit === "percent" ? `${k.value.toFixed(1)} %` : k.value.toLocaleString("en");
}

export function fmtPercent(p: number | null | undefined): string {
  return p === null || p === undefined ? "no data" : `${p.toFixed(1)} %`;
}

export type DeltaTone = "better" | "worse" | "same" | "none";

export interface DeltaView {
  text: string;
  tone: DeltaTone;
}

/** Direction is colour-independent: the sign and the word are always printed. */
export function deltaView(k: Kpi): DeltaView {
  if (k.delta == null || k.previous == null) {
    return { text: "no previous snapshot", tone: "none" };
  }
  if (k.delta === 0) return { text: "no change vs previous snapshot", tone: "same" };
  const up = k.delta > 0;
  const better = (k.goodDirection === "up") === up;
  const mag = Math.abs(k.delta).toLocaleString("en", { maximumFractionDigits: 1 });
  const unit = k.unit === "percent" ? " pts" : "";
  return {
    text: `${up ? "▲ +" : "▼ −"}${mag}${unit} vs previous snapshot`,
    tone: better ? "better" : "worse",
  };
}

export function shortType(t: string | null | undefined): string {
  if (typeof t !== "string" || t === "") return "(unknown type)";
  const parts = t.split("/");
  return parts.length > 1 ? parts.slice(1).join("/") : t;
}

export function toneOfPercent(p: number | null): "good" | "warn" | "bad" | "nodata" {
  if (p === null) return "nodata";
  if (p >= 90) return "good";
  if (p >= 70) return "warn";
  return "bad";
}

/** Query string for the explorer; the same keys are the API filter names. */
export function drillSearch(drill: Drill | null, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams();
  if (drill) {
    const tab = drill.tab ?? drill.page;
    if (tab) q.set("tab", tab);
    for (const [k, v] of Object.entries(drill.params ?? {})) {
      for (const x of Array.isArray(v) ? v : [v]) q.append(k, String(x));
    }
  }
  for (const [k, v] of Object.entries(extra)) q.set(k, v);
  return `?${q.toString()}`;
}

export function filtersFromSearch(search: URLSearchParams): Filters {
  const out: Filters = {};
  for (const key of FILTER_KEYS) {
    const v = search.getAll(key).filter(Boolean);
    if (v.length) out[key] = v;
  }
  return out;
}

export function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function toCsv(rows: unknown[][]): string {
  return rows.map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

const DIM_FILTER: Record<string, string> = {
  initiative: "initiative",
  assignment: "assignment",
  definition: "definition",
  resourceType: "rtype",
  subscription: "sub",
  resourceGroup: "rg",
  location: "loc",
  category: "category",
  effect: "effect",
  severity: "severity",
  state: "state",
};

/** The explorer filter that reproduces a breakdown row; null when the row cannot be filtered exactly. */
export function rowDrill(
  dim: string,
  row: { key: string; label: string },
): Record<string, string[]> | null {
  if (dim.startsWith("tag:")) {
    return row.label === "(untagged)" ? null : { tag: [`${dim.slice(4)}:${row.label}`] };
  }
  const key = DIM_FILTER[dim];
  if (!key) return null;
  if (dim === "resourceGroup") {
    return row.label === "(subscription scope)" ? null : { rg: [row.label] };
  }
  if (row.key === "__standalone") return null;
  return { [key]: [row.key] };
}
