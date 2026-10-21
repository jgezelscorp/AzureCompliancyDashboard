import type { PolicyApi } from "./policyClient";
import type {
  Breakdown,
  BreakdownRow,
  Kpi,
  PolicyOverview,
  Quality,
  ResourceRow,
  StateRow,
  Tally,
  TrendPoint,
} from "./policyTypes";

const AT = "2026-01-15T12:00:00+00:00";
const SUB = "00000000-0000-0000-0000-000000000000";

function kpi(partial: Partial<Kpi> & Pick<Kpi, "id" | "label">): Kpi {
  return {
    value: null,
    unit: "count",
    status: "ok",
    numerator: null,
    denominator: null,
    grain: "policy evaluation",
    formula: "Synthetic formula.",
    drill: { tab: "states", params: {} },
    goodDirection: "up",
    note: null,
    previous: null,
    delta: null,
    previousAt: null,
    sparkline: [],
    ...partial,
  };
}

const HEADLINE: Tally = {
  evaluations: 10,
  compliant: 6,
  nonCompliant: 3,
  exempt: 1,
  other: 0,
  percent: 66.7,
  resources: 8,
  nonCompliantResources: 3,
  nonCompliantPolicies: 2,
};

const ROWS: BreakdownRow[] = [
  { key: "i1", label: "Synthetic initiative A", evaluations: 6, compliant: 5, nonCompliant: 1, exempt: 0, other: 0, percent: 83.3, resources: 5, nonCompliantResources: 1 },
  { key: "i2", label: "Synthetic initiative B", evaluations: 4, compliant: 1, nonCompliant: 2, exempt: 1, other: 0, percent: 33.3, resources: 4, nonCompliantResources: 2 },
];

const STATE: StateRow = {
  resourceId: `/subscriptions/${SUB}/resourcegroups/rg-synthetic/providers/microsoft.storage/storageaccounts/stsynth`,
  resourceName: "stsynth",
  resourceType: "microsoft.storage/storageaccounts",
  subscriptionId: SUB,
  resourceGroup: "rg-synthetic",
  location: "swedencentral",
  policy: "Synthetic definition",
  definition: "/providers/microsoft.authorization/policydefinitions/synth-def-1",
  assignment: "Synthetic assignment",
  assignmentId: `/subscriptions/${SUB}/providers/microsoft.authorization/policyassignments/synth-a`,
  initiative: "Synthetic initiative B",
  initiativeId: "i2",
  state: "NonCompliant",
  effect: "audit",
  category: "Storage",
  severity: "high",
  evaluatedAt: AT,
};

const RESOURCE: ResourceRow = {
  resourceId: STATE.resourceId,
  name: "stsynth",
  resourceType: STATE.resourceType,
  subscriptionId: SUB,
  resourceGroup: "rg-synthetic",
  location: "swedencentral",
  tags: { owner: "synthetic-team" },
  evaluations: 3,
  compliant: 1,
  nonCompliant: 2,
  exempt: 0,
  other: 0,
  failingPolicies: 2,
  newestEvaluation: AT,
};

const POINTS: TrendPoint[] = [60, 62, 66.7].map((p, i) => ({
  runId: i + 1,
  at: `2026-01-1${3 + i}T12:00:00+00:00`,
  compliant: 6,
  nonCompliant: 3,
  evaluations: 10,
  nonCompliantResources: 3,
  percent: p,
  resourcePercent: 60,
  highImpactFailingPolicies: 1,
  regressions: 0,
  recoveries: i,
  newNonCompliant: 0,
  gapBefore: i === 2,
}));

export function createMockPolicyApi(): PolicyApi {
  const overview: PolicyOverview = {
    snapshotAt: AT,
    scope: { authorizedSubscriptions: 1, onboardedSubscriptions: 1, partial: false },
    filters: {},
    trendFiltered: false,
    kpis: [
      kpi({ id: "policyCompliance", label: "Azure Policy compliance", value: 66.7, unit: "percent", numerator: 6, denominator: 9, previous: 62, delta: 4.7, sparkline: [60, 62, 66.7] }),
      kpi({ id: "nonCompliantResources", label: "Non-compliant resources", value: 3, numerator: 3, denominator: 8, grain: "resource", goodDirection: "down", sparkline: [4, 3, 3], previous: 4, delta: -1 }),
      kpi({ id: "highImpactFailing", label: "High-impact failing policies", value: null, status: "no-data", goodDirection: "down", note: "No definition carries severity metadata." }),
      kpi({ id: "evidenceFreshness", label: "Evidence freshness", value: 100, unit: "percent", numerator: 10, denominator: 10 }),
    ],
    headline: HEADLINE,
    summary: ["As of 2026-01-15 12:00 UTC, 6 of 9 counted policy evaluations are compliant (66.7 %)."],
    samples: 3,
    sampleNote: "3 samples so far (collected every 6 h); trends are sampled, not continuous.",
    defender: { available: false, note: "Defender for Cloud data is shown separately." },
    machines: { available: false },
    labels: ["Azure Policy compliance %, check pass rate and coverage are separate metrics and are never combined."],
  };
  const breakdown: Breakdown = {
    dimension: "initiative",
    total: ROWS.length,
    rows: ROWS,
    grain: "policy evaluation",
    formula: "percent = compliant / (compliant + nonCompliant)",
    snapshotAt: AT,
  };
  const quality: Quality = {
    snapshotAt: AT,
    scope: overview.scope,
    freshness: { evaluations: 10, fresh: 10, percent: 100, newest: AT, oldest: AT, thresholdHours: 24 },
    inventory: { resources: 12, withEvaluations: 8, withoutEvaluations: 4, withoutEvaluationsTopTypes: [{ type: "microsoft.network/networkinterfaces", count: 4 }], note: "Inventory is limited to what Azure Resource Graph shows the collector." },
    metadata: { definitionsResolved: 5, definitionsWithSeverity: 0, evaluationsUncategorized: 1, evaluations: 10, note: "Categories come from definition metadata." },
    cisNotAssessed: "CIS results are 'not assessed' without an actual CIS assignment.",
    defender: overview.defender,
    limits: ["Exempt and Unknown evaluations are excluded from compliance %."],
  };
  const page = { total: 1, limit: 50, offset: 0, grain: "policy evaluation", snapshotAt: AT };
  return {
    overview: async () => overview,
    breakdown: async (dim) => ({ ...breakdown, dimension: dim }),
    topPolicies: async () => ({
      grain: "policy definition",
      rows: [{ definition: STATE.definition, name: "Synthetic definition", category: "Storage", effect: "audit", severity: "high", nonCompliant: 2, affectedResources: 2, assignments: 1, initiatives: ["Synthetic initiative B"] }],
    }),
    states: async () => ({ ...page, rows: [STATE], tally: HEADLINE }),
    resources: async () => ({ ...page, rows: [RESOURCE], grain: "resource" }),
    resource: async () => ({ ...RESOURCE, tally: HEADLINE, states: [STATE], snapshotAt: AT }),
    exemptions: async () => ({
      buckets: { active: 2, noExpiry: 0, expiring30: 1, expiring60: 0, expiring90: 0, expired: 1 },
      total: 3,
      filteredTotal: 1,
      items: [{ id: "e1", name: "Synthetic waiver", scope: "/subscriptions/x", assignment: "synth-a", category: "Waiver", expiresOn: "2026-02-01T00:00:00+00:00", daysToExpiry: 17, status: "active" }],
      grain: "exemption",
      note: "Buckets are exclusive.",
      snapshotAt: AT,
    }),
    trend: async () => ({
      points: POINTS,
      samples: POINTS.length,
      intervalHours: 6,
      note: "3 samples so far (collected every 6 h); trends are sampled, not continuous.",
      grain: "policy evaluation",
      gapNote: "A gap marker means the interval exceeded twice the collection interval.",
    }),
    filters: async () => ({
      options: {
        initiative: ROWS.map((r) => ({ key: r.key, label: r.label, evaluations: r.evaluations })),
        resourceType: [{ key: STATE.resourceType, label: STATE.resourceType, evaluations: 3 }],
        state: [{ key: "NonCompliant", label: "NonCompliant", evaluations: 3 }],
        tagKeys: ["owner"],
      },
      snapshotAt: AT,
    }),
    quality: async () => quality,
    machineCoverage: async () => ({ snapshotAt: AT, groups: [] }),
    machineDetail: async () => ({
      machine: { machineId: "m1", name: "vm-synthetic", kind: "AzureVM", subscriptionId: SUB, resourceGroup: "rg-synthetic", location: "swedencentral", osName: "Windows Server", osBuild: null, eligibility: "eligible", tags: {} },
      snapshotAt: AT,
      families: [],
      policy: { tally: HEADLINE, states: [] },
      history: [],
      historyNote: "0 samples so far.",
      labels: [],
    }),
  };
}
