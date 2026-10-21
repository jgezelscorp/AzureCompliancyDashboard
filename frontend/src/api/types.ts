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
