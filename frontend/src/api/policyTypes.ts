export type PolicyUnit = "percent" | "count";

export interface Drill {
  tab: string;
  params: Record<string, string[] | string | number>;
}

export interface Kpi {
  id: string;
  label: string;
  value: number | null;
  unit: PolicyUnit;
  status: "ok" | "no-data";
  numerator: number | null;
  denominator: number | null;
  grain: string;
  formula: string;
  drill: Drill | null;
  goodDirection: "up" | "down";
  note: string | null;
  previous: number | null;
  delta: number | null;
  previousAt: string | null;
  sparkline: number[];
}

export interface Tally {
  evaluations: number;
  compliant: number;
  nonCompliant: number;
  exempt: number;
  other: number;
  percent: number | null;
  resources: number;
  nonCompliantResources: number;
  nonCompliantPolicies: number;
}

export interface ScopeInfo {
  authorizedSubscriptions: number;
  onboardedSubscriptions: number;
  partial: boolean;
}

export interface MachineKpis {
  available: boolean;
  snapshotAt?: string;
  family?: string;
  checkPassRate?: { passed: number; failed: number; total: number; percent: number | null };
  coverage?: { eligible: number; assigned: number; freshReport: number; freshReportPercent: number | null };
  sparkline?: number[];
}

export interface DefenderInfo {
  available: boolean;
  note?: string;
  reason?: string;
}

export interface PolicyOverview {
  snapshotAt: string | null;
  scope: ScopeInfo;
  filters: Record<string, unknown>;
  trendFiltered: boolean;
  kpis: Kpi[];
  headline: Tally;
  summary: string[];
  samples: number;
  sampleNote: string;
  defender: DefenderInfo;
  machines: MachineKpis;
  labels: string[];
}

export interface BreakdownRow extends Omit<Tally, "nonCompliantPolicies"> {
  key: string;
  label: string;
  nonCompliantPolicies?: number;
}

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  rows: T[];
  grain: string;
  snapshotAt: string | null;
}

export interface Breakdown {
  dimension: string;
  total: number;
  rows: BreakdownRow[];
  grain: string;
  formula: string;
  snapshotAt: string | null;
}

export interface TopPolicy {
  definition: string;
  name: string;
  category: string;
  effect: string;
  severity: string;
  nonCompliant: number;
  affectedResources: number;
  assignments: number;
  initiatives: string[];
  domain?: string;
  domainConfidence?: string;
}

export interface StateRow {
  resourceId: string;
  resourceName: string;
  resourceType: string;
  subscriptionId: string;
  resourceGroup: string;
  location: string;
  policy: string;
  definition: string;
  assignment: string;
  assignmentId: string;
  initiative: string;
  initiativeId: string;
  state: string;
  effect: string;
  category: string;
  severity: string;
  domain?: string;
  domainConfidence?: string;
  evaluatedAt: string | null;
}

export interface StatesPage extends Page<StateRow> {
  tally: Tally;
}

export interface ResourceRow {
  resourceId: string;
  name: string;
  resourceType: string;
  subscriptionId: string;
  resourceGroup: string;
  location: string;
  tags: Record<string, string>;
  evaluations: number;
  compliant: number;
  nonCompliant: number;
  exempt: number;
  other: number;
  failingPolicies: number;
  newestEvaluation: string | null;
}

export interface ResourceDetail {
  resourceId: string;
  name: string;
  resourceType: string;
  subscriptionId: string;
  resourceGroup: string;
  location: string;
  tags: Record<string, string>;
  tally: Tally;
  states: Partial<StateRow>[];
  snapshotAt: string | null;
}

export interface ExemptionItem {
  id: string;
  name: string;
  scope: string;
  assignment: string;
  category: string;
  expiresOn: string | null;
  daysToExpiry: number | null;
  status: string;
}

export interface Exemptions {
  buckets: {
    active: number;
    noExpiry: number;
    expiring30: number;
    expiring60: number;
    expiring90: number;
    expired: number;
  };
  total: number;
  filteredTotal: number;
  items: ExemptionItem[];
  grain: string;
  note: string;
  snapshotAt: string | null;
}

export interface TrendPoint {
  runId: number;
  at: string;
  compliant: number;
  nonCompliant: number;
  evaluations: number;
  nonCompliantResources: number;
  percent: number | null;
  resourcePercent: number | null;
  highImpactFailingPolicies: number;
  regressions: number;
  recoveries: number;
  newNonCompliant: number;
  gapBefore: boolean;
  taxonomyVersion?: number | null;
}

export interface Trend {
  points: TrendPoint[];
  samples: number;
  intervalHours: number;
  note: string;
  grain: string;
  gapNote: string;
  taxonomyVersions?: number[];
  taxonomyChanged?: boolean;
  taxonomyNote?: string;
}

export interface FilterOption {
  key: string;
  label: string;
  evaluations: number;
}

export interface FilterOptions {
  options: Record<string, FilterOption[] | string[]> & { tagKeys: string[] };
  snapshotAt: string | null;
}

export interface Quality {
  snapshotAt: string | null;
  scope: ScopeInfo;
  freshness: {
    evaluations: number;
    fresh: number;
    percent: number | null;
    newest: string | null;
    oldest: string | null;
    thresholdHours: number;
  };
  inventory: {
    resources: number;
    withEvaluations: number;
    withoutEvaluations: number;
    withoutEvaluationsTopTypes: { type: string; count: number }[];
    note: string;
  };
  metadata: {
    definitionsResolved: number;
    definitionsWithSeverity: number;
    evaluationsUncategorized: number;
    evaluations: number;
    note: string;
  };
  cisNotAssessed: string;
  defender: DefenderInfo;
  limits: string[];
}

export interface MachineGroup {
  label: string;
  kind: string | null;
  machines: number;
  coverage: {
    eligible: number;
    assigned: number;
    usableReport: number;
    freshReport: number;
    assignmentPercent: number | null;
    freshReportPercent: number | null;
  };
  checkPassRate: { passed: number; failed: number; total: number; percent: number | null };
  policyCompliance: { compliant: number; nonCompliant: number; percent: number | null };
}

export interface MachineCoverage {
  snapshotAt: string | null;
  groups: MachineGroup[];
  note?: string;
  labels?: string[];
}

export interface MachineFamilyDetail {
  family: string;
  assigned: boolean;
  assignments: { name: string; version: string | null; complianceStatus: string | null; lastChecked: string | null }[];
  reports: { reportId: string; complianceStatus: string | null; endTime: string; checks: number }[];
  evidenceQuality: string | null;
  reportedState: string | null;
  checkPassRate: { passed: number; failed: number; total: number; percent: number | null };
  categories: {
    category: string;
    checks?: number;
    passed: number;
    total: number;
    percent: number | null;
    categorySource?: string;
  }[];
  note: string | null;
}

export interface MachineDetail {
  machine: {
    machineId: string;
    name: string;
    kind: string;
    subscriptionId: string;
    resourceGroup: string | null;
    location: string | null;
    osName: string | null;
    osBuild: string | null;
    eligibility: string | null;
    tags: Record<string, string>;
  };
  snapshotAt: string | null;
  families: MachineFamilyDetail[];
  policy: {
    tally: Tally;
    states: { policy: string; initiative: string; state: string; effect: string; evaluatedAt: string }[];
  };
  history: { snapshotAt: string; family: string; evidenceQuality: string; reportedState: string | null; green: boolean }[];
  historyNote: string;
  labels: string[];
}

/** Filter keys accepted by every /api/v1/policy list endpoint; also the URL query keys. */
export const FILTER_KEYS = [
  "sub",
  "rg",
  "loc",
  "rtype",
  "initiative",
  "assignment",
  "definition",
  "state",
  "category",
  "domain",
  "confidence",
  "effect",
  "severity",
  "tag",
  "maxAgeHours",
  "minAgeHours",
  "q",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
/** Repeated query parameters; maxAgeHours, minAgeHours and q carry a single value. */
export type Filters = Partial<Record<FilterKey, string[]>>;
