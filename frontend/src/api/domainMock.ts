import type { DomainApi } from "./domainClient";
import type {
  DomainCheckRow,
  DomainOverview,
  DomainRow,
  Frameworks,
  Overrides,
  OverrideRow,
  ProvenanceMix,
  QueueRow,
  Taxonomy,
} from "./domainTypes";

const AT = "2026-01-15T12:00:00+00:00";

const DOMAINS = [
  { id: "identity", label: "Identity and access" },
  { id: "network", label: "Network security" },
  { id: "data-protection", label: "Data protection" },
  { id: "other", label: "Other (uncategorized)" },
];

const TAXONOMY: Taxonomy = {
  taxonomyVersion: 2,
  domains: DOMAINS.map((d) => ({ ...d, frameworks: { cis: [{ id: "cis-5", label: "CIS section 5" }] } })),
  frameworks: { cis: { label: "CIS Controls", kind: "indicative" } },
  confidence: {
    override: "Decided by a reviewer or a repo-managed override.",
    source: "The definition's own category, mapped through the curated table.",
    "derived-high": "App rule on a section number or a curated check category.",
    "derived-low": "Keyword heuristic on the display name; review recommended.",
    unmapped: "Nothing matched; the item is in 'Other' and in the review queue.",
  },
  disclaimer: "Framework families are indicative related controls, not compliance claims or certification.",
  labels: ["A domain is an app-curated grouping (taxonomy v2); it is not a benchmark or certification mapping."],
};

function mix(by: Partial<Record<string, number>>): ProvenanceMix {
  const get = (k: string) => by[k] ?? 0;
  const total = Object.values(by).reduce<number>((n, v) => n + (v ?? 0), 0);
  const pct = (n: number) => (total === 0 ? null : Math.round((n / total) * 1000) / 10);
  return {
    total,
    byConfidence: {
      override: get("override"),
      source: get("source"),
      "derived-high": get("derived-high"),
      "derived-low": get("derived-low"),
      unmapped: get("unmapped"),
    },
    unmapped: get("unmapped"),
    unmappedPercent: pct(get("unmapped")),
    sourcePercent: pct(get("source")),
    derivedPercent: pct(get("derived-high") + get("derived-low")),
    overridePercent: pct(get("override")),
  };
}

function policyTally(key: string, label: string, compliant: number, nonCompliant: number, resources: number) {
  const evaluations = compliant + nonCompliant;
  return {
    key,
    label,
    evaluations,
    compliant,
    nonCompliant,
    exempt: 0,
    other: 0,
    percent: evaluations === 0 ? null : Math.round((compliant / evaluations) * 1000) / 10,
    resources,
    nonCompliantResources: nonCompliant,
  };
}

const ROWS: DomainRow[] = [
  {
    domain: "identity",
    label: "Identity and access",
    policy: policyTally("identity", "Identity and access", 8, 2, 6),
    machine: { AzureWindowsBaseline: { checks: 4, machines: 3, passed: 9, total: 12, percent: 75 } },
    frameworks: { cis: ["cis-5"] },
  },
  {
    domain: "network",
    label: "Network security",
    policy: policyTally("network", "Network security", 1, 3, 4),
    machine: {},
    frameworks: { cis: ["cis-5"] },
  },
  {
    domain: "data-protection",
    label: "Data protection",
    policy: null,
    machine: { CISWindowsSecurityBaseline: { checks: 2, machines: 2, passed: 1, total: 4, percent: 25 } },
    frameworks: {},
  },
  {
    domain: "other",
    label: "Other (uncategorized)",
    policy: policyTally("other", "Other (uncategorized)", 1, 0, 1),
    machine: {},
    frameworks: {},
  },
];

const POLICY_MIX = mix({ source: 5, "derived-high": 2, "derived-low": 2, override: 1, unmapped: 2 });
const CHECK_MIX = mix({ source: 3, "derived-high": 2, unmapped: 1 });

export const MOCK_QUEUE: QueueRow[] = [
  {
    kind: "policy",
    key: "/providers/microsoft.authorization/policydefinitions/synth-def-9",
    name: "Synthetic unmapped policy",
    family: null,
    category: null,
    domain: "other",
    domainSource: "unmapped",
    domainConfidence: "unmapped",
    evaluations: 4,
    nonCompliant: 1,
    suggestedDomain: "network",
    domainLabel: "Other (uncategorized)",
  },
  {
    kind: "check",
    key: "synthetic-check-1",
    name: "Synthetic keyword-derived check",
    family: "AzureWindowsBaseline",
    category: "Misc",
    domain: "identity",
    domainSource: "derived",
    domainConfidence: "derived-low",
    evaluations: 6,
    nonCompliant: 2,
    suggestedDomain: null,
    domainLabel: "Identity and access",
  },
];

export const MOCK_CHECKS: DomainCheckRow[] = [
  {
    checkKey: "synthetic-check-1",
    name: "Synthetic keyword-derived check",
    family: "AzureWindowsBaseline",
    category: "Misc",
    domain: "identity",
    domainSource: "derived",
    domainConfidence: "derived-low",
    domainVersion: 2,
    machinesPassed: 4,
    machinesFailed: 2,
  },
];

export interface MockDomainOptions {
  /** Server-side gate (ACD anchor configured). */
  gateEnabled?: boolean;
  /** Caller-side permission from /auth/capabilities. */
  canEdit?: boolean;
}

export function createMockDomainApi(opts: MockDomainOptions = {}): DomainApi {
  const gateEnabled = opts.gateEnabled ?? false;
  const canEdit = opts.canEdit ?? false;
  let overrides: OverrideRow[] = [
    { id: 1, target: "policy", kind: "exact", pattern: "synth-def-1", domain: "network", note: "reviewed", createdBy: "synthetic-oid", createdAt: AT },
  ];
  let nextId = 2;
  const overview = (): DomainOverview => ({
    taxonomyVersion: 2,
    snapshotAt: AT,
    machineSnapshotAt: AT,
    domains: ROWS,
    provenance: { policies: POLICY_MIX, checks: CHECK_MIX },
    grain: {
      policy: "policy evaluation; percent = compliant / (compliant + nonCompliant)",
      machine: "check result on one machine; percent = passed / results (fresh reports)",
    },
    disclaimer: TAXONOMY.disclaimer,
    filters: {},
    labels: TAXONOMY.labels,
  });
  const frameworks: Frameworks = {
    taxonomyVersion: 2,
    frameworks: [
      {
        framework: "cis",
        label: "CIS Controls",
        kind: "indicative",
        families: [
          { family: "cis-5", label: "CIS section 5", domains: ["identity", "network"], policies: 6, evaluations: 14, compliant: 9, nonCompliant: 5, percent: 64.3, checks: 4, checksFailing: 2 },
        ],
      },
    ],
    additive: false,
    note: "Distinct counts per family. A domain can relate to several families, so family rows overlap and must not be summed. Indicative related controls, not compliance claims.",
    disclaimer: TAXONOMY.disclaimer,
    snapshotAt: AT,
  };
  return {
    taxonomy: async () => TAXONOMY,
    overview: async () => overview(),
    frameworks: async () => frameworks,
    provenance: async () => ({ policies: POLICY_MIX, checks: CHECK_MIX, grain: "distinct definitions" }),
    queue: async (p) => {
      const rows = MOCK_QUEUE.filter(
        (r) =>
          (p.kind === "all" || r.kind === p.kind) &&
          (p.confidence.length === 0 || p.confidence.includes(r.domainConfidence)) &&
          (!p.q || `${r.name} ${r.key}`.toLowerCase().includes(p.q.toLowerCase())),
      );
      return {
        total: rows.length,
        limit: p.limit,
        offset: p.offset,
        summary: { policy: rows.filter((r) => r.kind === "policy").length, check: rows.filter((r) => r.kind === "check").length },
        confidences: p.confidence,
        rows: rows.slice(p.offset, p.offset + p.limit),
        taxonomyVersion: 2,
        snapshotAt: AT,
      };
    },
    checks: async (domain) => ({
      domain,
      domainLabel: DOMAINS.find((d) => d.id === domain)?.label ?? domain,
      total: MOCK_CHECKS.filter((c) => c.domain === domain).length,
      rows: MOCK_CHECKS.filter((c) => c.domain === domain),
      grain: "distinct check; machinesFailed / machinesPassed are machines with a fresh report",
      taxonomyVersion: 2,
    }),
    overrides: async (): Promise<Overrides> => ({
      overrides,
      repoOverrides: 0,
      gateEnabled,
      editing: gateEnabled
        ? "Overrides are created by users with Azure deployments/write on the configuration anchor resource group."
        : "The shared-configuration gate is not enabled in this deployment, so overrides cannot be edited here. Use ACD_DOMAIN_OVERRIDES / ACD_DOMAIN_OVERRIDES_FILE.",
      taxonomyVersion: 2,
    }),
    createOverride: async (body) => {
      const row: OverrideRow = { id: nextId++, kind: "exact", note: body.note ?? null, createdBy: "synthetic-oid", createdAt: AT, target: body.target, pattern: body.pattern, domain: body.domain };
      overrides = [...overrides, row];
      return row;
    },
    deleteOverride: async (id) => {
      overrides = overrides.filter((o) => o.id !== id);
    },
    capabilities: async () => ({ canEditSharedConfig: canEdit, reason: canEdit ? "allowed" : "not permitted" }),
  };
}
