/** Synthetic development data (VITE_USE_MOCK_DATA=true). Never real evidence; all IDs are placeholders. */
import type { MetricsApi } from "./client";
import type {
  CategoryRow,
  CheckMachineRow,
  CheckRow,
  ComplianceState,
  EvidenceQuality,
  FamilyMetrics,
  HistoryPoint,
  MachineRow,
  MetricFamily,
  ScopeInfo,
} from "./types";

export const MOCK_SUB_A = "00000000-0000-0000-0000-000000000000";
export const MOCK_SUB_B = "00000000-0000-0000-0000-000000000001";
const SNAPSHOT_AT = "2026-01-15T12:00:00+00:00";

interface MockCheck {
  key: string;
  name: string;
  category: string;
  pass: boolean;
}
interface MockEvidence {
  quality: EvidenceQuality;
  state: ComplianceState | null;
  checks: MockCheck[];
}
interface MockMachine {
  name: string;
  sub: string;
  kind: "AzureVM" | "ArcMachine";
  evidence: Record<MetricFamily, MockEvidence>;
}

const AZ_CHECKS = (failing: string[]): MockCheck[] =>
  [
    ["[Audit Policy]Audit Logon", "Audit Logon events", "Audit Policy"],
    ["[Audit Policy]Audit Process Creation", "Audit process creation", "Audit Policy"],
    ["[Security Options]Limit blank passwords", "Limit blank password use", "Security Options"],
    ["[Security Options]Rename Administrator", "Rename administrator account", "Security Options"],
    ["[Windows Firewall]Domain profile on", "Domain firewall profile enabled", "Windows Firewall"],
  ].map(([key, name, category]) => ({ key, name, category, pass: !failing.includes(key) }));

const CIS_CHECKS = (failing: string[]): MockCheck[] =>
  [
    ["1.1.1", "Password history", "Account Policies"],
    ["1.1.2", "Maximum password age", "Account Policies"],
    ["2.3.1", "Guest account status", "Security Options"],
  ].map(([key, name, category]) => ({ key, name, category, pass: !failing.includes(key) }));

const none: MockEvidence = { quality: "MissingAssignment", state: null, checks: [] };

const MACHINES: MockMachine[] = [
  {
    name: "demo-vm-01",
    sub: MOCK_SUB_A,
    kind: "AzureVM",
    evidence: {
      AzureWindowsBaseline: {
        quality: "Fresh",
        state: "NonCompliant",
        checks: AZ_CHECKS(["[Audit Policy]Audit Logon"]),
      },
      CISWindowsSecurityBaseline: {
        quality: "Fresh",
        state: "NonCompliant",
        checks: CIS_CHECKS(["1.1.2"]),
      },
    },
  },
  {
    name: "demo-vm-02",
    sub: MOCK_SUB_A,
    kind: "AzureVM",
    evidence: {
      AzureWindowsBaseline: { quality: "Fresh", state: "Compliant", checks: AZ_CHECKS([]) },
      CISWindowsSecurityBaseline: { quality: "Stale", state: "Compliant", checks: CIS_CHECKS([]) },
    },
  },
  {
    name: "demo-arc-01",
    sub: MOCK_SUB_B,
    kind: "ArcMachine",
    evidence: {
      AzureWindowsBaseline: {
        quality: "Fresh",
        state: "NonCompliant",
        checks: AZ_CHECKS([
          "[Security Options]Limit blank passwords",
          "[Windows Firewall]Domain profile on",
        ]),
      },
      CISWindowsSecurityBaseline: none,
    },
  },
  {
    name: "demo-arc-02",
    sub: MOCK_SUB_B,
    kind: "ArcMachine",
    evidence: {
      AzureWindowsBaseline: { quality: "NoReport", state: null, checks: [] },
      CISWindowsSecurityBaseline: none,
    },
  },
];

function machineId(m: MockMachine): string {
  const type = m.kind === "AzureVM" ? "Microsoft.Compute/virtualMachines" : "Microsoft.HybridCompute/machines";
  return `/subscriptions/${m.sub}/resourceGroups/demo-rg/providers/${type}/${m.name}`;
}

function inScope(sub?: string): MockMachine[] {
  return MACHINES.filter((m) => !sub || m.sub === sub);
}

function ratio(n: number, d: number): number | null {
  return d === 0 ? null : Math.round((1000 * n) / d) / 10;
}

function familyMetrics(family: MetricFamily, machines: MockMachine[]): FamilyMetrics {
  const ev = machines.map((m) => m.evidence[family]);
  const fresh = ev.filter((e) => e.quality === "Fresh");
  const checks = fresh.flatMap((e) => e.checks);
  const passed = checks.filter((c) => c.pass).length;
  const compliant = fresh.filter((e) => e.state === "Compliant").length;
  const nonCompliant = fresh.filter((e) => e.state === "NonCompliant").length;
  const assigned = ev.filter((e) => e.quality !== "MissingAssignment").length;
  const usable = ev.filter((e) => ["Fresh", "Stale", "UnknownAge"].includes(e.quality)).length;
  const n = machines.length;
  return {
    snapshotId: 1,
    runId: 1,
    snapshotAt: SNAPSHOT_AT,
    collectionStatus: "succeeded",
    family,
    policyCompliance: {
      compliant,
      nonCompliant,
      exempt: 0,
      other: 0,
      percent: ratio(compliant, compliant + nonCompliant),
    },
    checkPassRate: {
      passed,
      failed: checks.length - passed,
      total: checks.length,
      percent: ratio(passed, checks.length),
      reportsExcludedAsNotFresh: ev.filter((e) => e.quality === "Stale").length,
    },
    coverage: {
      eligible: n,
      unknownEligibility: 0,
      assigned,
      usableReport: usable,
      freshReport: fresh.length,
      assignmentPercent: ratio(assigned, n),
      usableReportPercent: ratio(usable, n),
      freshReportPercent: ratio(fresh.length, n),
    },
    note:
      family === "CISWindowsSecurityBaseline"
        ? "Synthetic demo data: not live CIS evidence; applicability is unverified."
        : null,
  };
}

const SCOPE: ScopeInfo = { authorizedSubscriptions: 2, onboardedSubscriptions: 2, partial: false };
const LABELS = [
  "Azure Policy compliance %, check pass rate and coverage are separate metrics and are never combined.",
  "Results describe Azure Policy / Machine Configuration reports; they are not a CIS, ISO, NIS2 or DORA certification or attestation.",
  "No data is not compliance: missing or stale evidence is never green.",
];

function freshChecks(family: MetricFamily, sub?: string) {
  return inScope(sub).flatMap((m) =>
    m.evidence[family].quality === "Fresh" ? m.evidence[family].checks.map((c) => ({ m, c })) : [],
  );
}

function history(family: MetricFamily): HistoryPoint[] {
  const base = familyMetrics(family, MACHINES);
  return Array.from({ length: 8 }, (_, i) => {
    const drift = (i - 7) * 2;
    const at = new Date(Date.parse(SNAPSHOT_AT) + (i - 7) * 24 * 3600 * 1000).toISOString();
    const pct = base.checkPassRate.percent;
    return {
      snapshotId: i + 1,
      snapshotAt: at,
      family,
      collectionStatus: "succeeded",
      machineSummary: { machines: 4, fresh: 3, green: 1 },
      policyCompliance: base.policyCompliance,
      coverage: base.coverage,
      checkPassRate: {
        ...base.checkPassRate,
        percent: pct === null ? null : Math.max(0, Math.min(100, pct + drift)),
      },
    };
  });
}

export function createMockApi(): MetricsApi {
  const resolve = <T,>(v: T) => Promise.resolve(v);
  return {
    latest: () =>
      resolve({
        snapshotAt: SNAPSHOT_AT,
        dataStale: true,
        freshnessHours: 24,
        families: (["AzureWindowsBaseline", "CISWindowsSecurityBaseline"] as const).map((f) =>
          familyMetrics(f, MACHINES),
        ),
        labels: LABELS,
        scope: SCOPE,
      }),
    scopes: () =>
      resolve({
        snapshotAt: SNAPSHOT_AT,
        scope: SCOPE,
        scopes: [MOCK_SUB_A, MOCK_SUB_B].map((s) => ({
          subscriptionId: s,
          machineCount: inScope(s).length,
          families: (["AzureWindowsBaseline", "CISWindowsSecurityBaseline"] as const).map((f) => {
            const { family, policyCompliance, checkPassRate, coverage } = familyMetrics(f, inScope(s));
            return { family, policyCompliance, checkPassRate, coverage };
          }),
        })),
      }),
    history: (family) =>
      resolve({
        points: history(family),
        aggregatesIncluded: true,
        samplingNote: "Samples at collection times; not continuous assessment.",
        labels: LABELS,
        scope: SCOPE,
      }),
    machines: (family) => {
      const machines: MachineRow[] = MACHINES.map((m) => ({
        machineId: machineId(m),
        name: m.name,
        kind: m.kind,
        subscriptionId: m.sub,
        evidenceQuality: m.evidence[family].quality,
        reportedState: m.evidence[family].state,
        green: m.evidence[family].quality === "Fresh" && m.evidence[family].state === "Compliant",
      }));
      return resolve({ snapshotAt: SNAPSHOT_AT, family, total: machines.length, machines });
    },
    categories: (family, sub) => {
      const acc = new Map<string, { keys: Set<string>; passed: number; total: number }>();
      for (const { c } of freshChecks(family, sub)) {
        const a = acc.get(c.category) ?? { keys: new Set<string>(), passed: 0, total: 0 };
        a.keys.add(c.key);
        a.total += 1;
        a.passed += c.pass ? 1 : 0;
        acc.set(c.category, a);
      }
      const categories: CategoryRow[] = [...acc.entries()].map(([category, a]) => ({
        category,
        checks: a.keys.size,
        passed: a.passed,
        total: a.total,
        percent: ratio(a.passed, a.total),
      }));
      return resolve({ snapshotAt: SNAPSHOT_AT, categories });
    },
    checks: (family, category, sub) => {
      const acc = new Map<string, CheckRow>();
      for (const { c } of freshChecks(family, sub)) {
        if (c.category !== category) continue;
        const row = acc.get(c.key) ?? {
          checkKey: c.key,
          name: c.name,
          severity: null,
          benchmarkControlId: family === "CISWindowsSecurityBaseline" ? c.key : null,
          machinesPassed: 0,
          machinesFailed: 0,
        };
        if (c.pass) row.machinesPassed += 1;
        else row.machinesFailed += 1;
        acc.set(c.key, row);
      }
      return resolve({
        snapshotAt: SNAPSHOT_AT,
        checks: [...acc.values()].sort((a, b) => b.machinesFailed - a.machinesFailed),
      });
    },
    checkMachines: (family, key, sub) => {
      const machines: CheckMachineRow[] = freshChecks(family, sub)
        .filter(({ c }) => c.key === key)
        .map(({ m, c }) => ({
          machineId: machineId(m),
          name: m.name,
          subscriptionId: m.sub,
          status: c.pass ? "Compliant" : "NonCompliant",
          reasons: c.pass ? [] : [{ phrase: "Synthetic: value differs from baseline", expected: "1", actual: "0" }],
        }));
      return resolve({ snapshotAt: SNAPSHOT_AT, machines });
    },
    runs: () =>
      resolve({
        runs: [
          { runId: 1, startedAt: SNAPSHOT_AT, finishedAt: SNAPSHOT_AT, status: "succeeded", hasError: false },
        ],
      }),
  };
}
