import type { Confidence, DomainChecks, DomainOverview, Frameworks, QueueRow } from "../api/domainTypes";
import { CONFIDENCES } from "../api/domainTypes";
import type { StateRow } from "../api/policyTypes";
import { FAMILY_LABEL } from "./format";
import { fmtPercent, toCsv } from "./policyFormat";

export interface ConfidenceMeta {
  label: string;
  icon: string;
  tone: "good" | "warn" | "bad" | "nodata" | "stale";
  hint: string;
}

/** Text and icon always carry the meaning; colour is only reinforcement. */
export const CONFIDENCE_META: Record<Confidence, ConfidenceMeta> = {
  override: { label: "Override", icon: "✎", tone: "stale", hint: "Decided by a reviewer or a repo-managed override." },
  source: { label: "Source category", icon: "✔", tone: "good", hint: "From the item's own category through the curated table." },
  "derived-high": { label: "Derived (high)", icon: "◆", tone: "good", hint: "App rule on a section number or curated category." },
  "derived-low": { label: "Derived (low)", icon: "▲", tone: "warn", hint: "Keyword heuristic on the name; review recommended." },
  unmapped: { label: "Unmapped", icon: "∅", tone: "nodata", hint: "Nothing matched; the item is in Other and in the review queue." },
};

export function isConfidence(v: string | null | undefined): v is Confidence {
  return (CONFIDENCES as readonly string[]).includes(v ?? "");
}

export const DISCLAIMER_FALLBACK = "Framework families are indicative related controls, not compliance claims or certification.";

export function familyLabel(family: string): string {
  return (FAMILY_LABEL as Record<string, string>)[family] ?? family;
}

export function confidenceLabel(v: string | null | undefined): string {
  return isConfidence(v) ? CONFIDENCE_META[v].label : "Not classified";
}

/** Rows kept when the Overview is limited to selected domains (empty selection keeps all). */
export function visibleDomains(o: DomainOverview, selected: string[]) {
  return selected.length === 0 ? o.domains : o.domains.filter((d) => selected.includes(d.domain));
}

export function overviewDomainCsv(o: DomainOverview, fw: Frameworks | null, selected: string[]): unknown[][] {
  const rows: unknown[][] = [
    [],
    ["Security domains (taxonomy v" + o.taxonomyVersion + "; app-curated grouping, not a benchmark or certification mapping)"],
    ["Domain filter", selected.length ? selected.join(" | ") : "none (all domains)"],
    ["Domain", "Domain id", "Policy % compliant", "Policy compliant", "Policy non-compliant", "Policy evaluations", "Machine baseline family", "Machine check pass rate %", "Checks passed", "Check results", "Distinct checks"],
  ];
  for (const d of visibleDomains(o, selected)) {
    const fams = Object.entries(d.machine);
    const p = d.policy;
    const policyCells = p ? [p.percent ?? "no data", p.compliant, p.nonCompliant, p.evaluations] : ["no data", "", "", ""];
    if (fams.length === 0) rows.push([d.label, d.domain, ...policyCells, "", "no data", "", "", ""]);
    for (const [fam, t] of fams) rows.push([d.label, d.domain, ...policyCells, familyLabel(fam), t.percent ?? "no data", t.passed, t.total, t.checks]);
  }
  rows.push([o.grain.policy], [o.grain.machine], ["Policy compliance % and machine check pass rate are separate metrics and are never combined."]);
  rows.push([], ["Domain provenance", "Total", "Source %", "Derived %", "Override %", "Unmapped %", "Unmapped count"]);
  for (const [name, m] of [["Policies", o.provenance.policies], ["Checks", o.provenance.checks]] as const) {
    rows.push([name, m.total, m.sourcePercent ?? "", m.derivedPercent ?? "", m.overridePercent ?? "", m.unmappedPercent ?? "", m.unmapped]);
  }
  if (fw) {
    rows.push([], ["Framework families (indicative, non-additive)", "Family", "Distinct policies", "Distinct checks", "Policy % compliant"]);
    for (const f of fw.frameworks) for (const fam of f.families) rows.push([f.label, fam.label, fam.policies, fam.checks, fam.percent ?? "no data"]);
    rows.push([fw.note], [fw.disclaimer]);
  } else {
    rows.push([DISCLAIMER_FALLBACK]);
  }
  rows.push([o.disclaimer]);
  return rows;
}

export function statesCsv(states: StateRow[], filters: Record<string, string[] | undefined>): string {
  const active = Object.entries(filters).flatMap(([k, v]) => (v ?? []).map((x) => `${k}=${x}`));
  return toCsv([
    ["Policy states (reporting aid, not a certification)"],
    ["Active filters", active.join(" & ") || "none"],
    ["Resource", "Type", "Resource group", "Policy", "Initiative", "State", "Effect", "Category", "Domain", "Domain provenance", "Evaluated"],
    ...states.map((s) => [s.resourceName, s.resourceType, s.resourceGroup, s.policy, s.initiative, s.state, s.effect, s.category, s.domain ?? "", confidenceLabel(s.domainConfidence), s.evaluatedAt ?? ""]),
  ]);
}

export function queueCsv(rows: QueueRow[], total: number): string {
  return toCsv([
    ["Needs-category queue (items whose domain is unmapped or low confidence)", `${rows.length} of ${total} rows`],
    ["Kind", "Name", "Key", "Baseline family", "Category", "Current domain", "Provenance", "Suggested domain", "Evaluations", "Non-compliant"],
    ...rows.map((r) => [r.kind, r.name, r.key, r.family ? familyLabel(r.family) : "", r.category ?? "", r.domain, confidenceLabel(r.domainConfidence), r.suggestedDomain ?? "", r.evaluations, r.nonCompliant]),
  ]);
}

export function domainChecksCsv(c: DomainChecks): string {
  return toCsv([
    [`Checks in security domain ${c.domainLabel} (${c.domain}); each check counts once per domain`],
    [c.grain],
    ["Check", "Key", "Baseline family", "Category", "Domain", "Provenance", "Machines failing", "Machines passing"],
    ...c.rows.map((r) => [r.name, r.checkKey, familyLabel(r.family), r.category ?? "", r.domain, confidenceLabel(r.domainConfidence), r.machinesFailed, r.machinesPassed]),
  ]);
}

export function pctText(p: number | null | undefined): string {
  return fmtPercent(p);
}

export function downloadCsv(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
