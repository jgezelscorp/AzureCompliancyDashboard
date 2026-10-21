/** Types mirroring backend/app/models.py and contracts/schemas (camelCase wire format). */

export interface HealthResponse {
  status: "ok";
  version: string;
}

export interface InfoResponse {
  version: string;
  environment: string;
  freshnessHours: number;
  retentionMonths: number;
  subscriptionCount: number;
}

export interface BundleSummary {
  machines: number;
  assignments: number;
  reports: number;
  checks: number;
  policyStates: number;
  exemptions: number;
  synthetic: boolean;
}

export type BaselineFamily =
  | "AzureWindowsBaseline"
  | "CISWindowsSecurityBaseline"
  | "Other"
  | "Unknown";
export type MachineKind = "AzureVM" | "ArcMachine";
export type ComplianceState = "Compliant" | "NonCompliant" | "Pending" | "Unknown";

export interface Machine {
  machineId: string;
  name: string;
  kind: MachineKind;
  subscriptionId: string;
  resourceGroup: string;
  location?: string;
  osType: "Windows" | "Linux" | "Unknown";
  osName?: string | null;
  osBuild?: string | null;
  eligibility: "Eligible" | "NotEligible" | "Unknown";
  tags?: Record<string, string>;
}

/** Metrics API (backend/app/api/metrics.py). The three metrics are never combined. */
export type MetricFamily = "AzureWindowsBaseline" | "CISWindowsSecurityBaseline";

export type EvidenceQuality =
  | "Fresh"
  | "Stale"
  | "UnknownAge"
  | "NoReport"
  | "MissingAssignment"
  | "UnknownApplicability";

export interface PolicyCompliance {
  compliant: number;
  nonCompliant: number;
  exempt: number;
  other: number;
  percent: number | null;
}

export interface CheckPassRate {
  passed: number;
  failed: number;
  total: number;
  percent: number | null;
  reportsExcludedAsNotFresh: number;
}

export interface Coverage {
  eligible: number;
  unknownEligibility: number;
  assigned: number;
  usableReport: number;
  freshReport: number;
  assignmentPercent: number | null;
  usableReportPercent: number | null;
  freshReportPercent: number | null;
}

export interface FamilyMetrics {
  snapshotId: number;
  runId: number;
  snapshotAt: string;
  collectionStatus: string;
  family: MetricFamily;
  policyCompliance: PolicyCompliance;
  checkPassRate: CheckPassRate;
  coverage: Coverage;
  note?: string | null;
}

export interface ScopeInfo {
  authorizedSubscriptions: number;
  onboardedSubscriptions: number;
  partial: boolean;
}

export interface LatestMetrics {
  snapshotAt: string | null;
  dataStale: boolean;
  freshnessHours?: number;
  families: FamilyMetrics[];
  labels: string[];
  scope: ScopeInfo;
}

export interface ScopeMetrics {
  subscriptionId: string;
  machineCount: number;
  families: Pick<FamilyMetrics, "family" | "policyCompliance" | "checkPassRate" | "coverage">[];
}

export interface ScopesResponse {
  snapshotAt: string | null;
  scopes: ScopeMetrics[];
  scope: ScopeInfo;
}

export interface CategoryRow {
  category: string;
  checks: number;
  passed: number;
  total: number;
  percent: number | null;
}

export interface CheckRow {
  checkKey: string;
  name: string;
  severity: string | null;
  benchmarkControlId: string | null;
  machinesPassed: number;
  machinesFailed: number;
}

export interface CheckMachineRow {
  machineId: string;
  name: string;
  subscriptionId: string;
  status: "Compliant" | "NonCompliant";
  reasons: { phrase: string; expected?: string | null; actual?: string | null }[];
}

export interface MachineRow {
  machineId: string;
  name: string;
  kind: MachineKind;
  subscriptionId: string;
  evidenceQuality: EvidenceQuality;
  reportedState: ComplianceState | null;
  green: boolean;
}

export interface MachinesResponse {
  snapshotAt: string | null;
  family: MetricFamily;
  total: number;
  machines: MachineRow[];
}

export interface HistoryPoint {
  snapshotId: number;
  snapshotAt: string;
  family: MetricFamily;
  collectionStatus: string;
  machineSummary: { machines: number; fresh: number; green: number };
  policyCompliance?: PolicyCompliance;
  checkPassRate?: CheckPassRate;
  coverage?: Coverage;
}

export interface HistoryResponse {
  points: HistoryPoint[];
  aggregatesIncluded: boolean;
  samplingNote: string;
  labels: string[];
  scope: ScopeInfo;
}

export interface CollectionRun {
  runId: number;
  startedAt: string;
  finishedAt: string | null;
  status: string;
  hasError: boolean;
}

export interface AuthConfig {
  authority: string;
  tenantId: string;
  spaClientId: string;
  apiScope: string;
}
