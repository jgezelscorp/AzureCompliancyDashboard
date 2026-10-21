import type { FamilyMetrics } from "../api/types";
import { formatPercent, toneFor } from "../lib/format";
import { MetricCard } from "./common";

/** The three metrics side by side and always separate; stale evidence is never shown green. */
export function FamilyMetricCards({ metrics, stale }: { metrics: FamilyMetrics; stale: boolean }) {
  const { policyCompliance: pc, checkPassRate: cp, coverage: cv } = metrics;
  return (
    <div className="cards">
      <MetricCard
        title="Azure Policy compliance"
        value={formatPercent(pc.percent)}
        tone={toneFor(pc.percent, stale)}
        detail={`${pc.compliant} compliant, ${pc.nonCompliant} non-compliant, ${pc.exempt} exempt, ${pc.other} other policy states`}
      />
      <MetricCard
        title="Check pass rate"
        value={formatPercent(cp.percent)}
        tone={toneFor(cp.percent, stale)}
        detail={`${cp.passed} of ${cp.total} checks pass on fresh reports; ${cp.reportsExcludedAsNotFresh} stale report(s) excluded`}
      />
      <MetricCard
        title="Fresh-report coverage"
        value={formatPercent(cv.freshReportPercent)}
        tone={toneFor(cv.freshReportPercent, stale)}
        detail={`${cv.freshReport} of ${cv.eligible} eligible machines have fresh evidence (${cv.assigned} assigned, ${cv.usableReport} with a report, ${cv.unknownEligibility} with unknown applicability)`}
      />
    </div>
  );
}
