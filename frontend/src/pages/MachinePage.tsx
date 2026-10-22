import { Link, useSearchParams } from "react-router-dom";
import { usePolicyApi } from "../api/policyContext";
import type { MachineFamilyDetail } from "../api/policyTypes";
import { Empty, ErrorState, Loading } from "../components/common";
import { useAsync } from "../hooks/useAsync";
import { FAMILY_LABEL } from "../lib/format";
import { fmtPercent, formatWhen } from "../lib/policyFormat";
import type { MetricFamily } from "../api/types";

function FamilySection({ f }: { f: MachineFamilyDetail }) {
  const label = FAMILY_LABEL[f.family as MetricFamily] ?? f.family;
  return (
    <section className="panel" aria-label={label}>
      <h3>{label}</h3>
      {!f.assigned ? (
        <Empty>{f.note ?? "Not assessed: no guest assignment."}</Empty>
      ) : (
        <>
          <p>
            Evidence: <strong>{f.evidenceQuality ?? "unknown"}</strong> · reported state: <strong>{f.reportedState ?? "not assessed"}</strong> · check pass rate {fmtPercent(f.checkPassRate.percent)} ({f.checkPassRate.passed} of {f.checkPassRate.total} checks)
          </p>
          <h4>Guest assignments</h4>
          <table className="data-table">
            <caption className="sr-only">Guest assignments</caption>
            <thead><tr><th scope="col">Configuration</th><th scope="col">Version</th><th scope="col">Status</th><th scope="col">Last checked</th></tr></thead>
            <tbody>
              {f.assignments.map((a) => (
                <tr key={a.name}><th scope="row">{a.name}</th><td>{a.version ?? "n/a"}</td><td>{a.complianceStatus ?? "unknown"}</td><td>{formatWhen(a.lastChecked)}</td></tr>
              ))}
            </tbody>
          </table>
          <h4>Reports</h4>
          <table className="data-table">
            <caption className="sr-only">Guest reports</caption>
            <thead><tr><th scope="col">Report</th><th scope="col">Status</th><th scope="col">Ended</th><th scope="col" className="num">Checks</th></tr></thead>
            <tbody>
              {f.reports.map((r) => (
                <tr key={r.reportId}><th scope="row">{(r.reportId ?? "").slice(-12)}</th><td>{r.complianceStatus ?? "unknown"}</td><td>{formatWhen(r.endTime)}</td><td className="num">{r.checks}</td></tr>
              ))}
            </tbody>
          </table>
          <h4>Checks by derived category</h4>
          <table className="data-table">
            <caption className="sr-only">Checks by derived category</caption>
            <thead><tr><th scope="col">Category</th><th scope="col" className="num">Passed</th><th scope="col" className="num">Total</th><th scope="col" className="num">Pass rate</th></tr></thead>
            <tbody>
              {f.categories.map((c) => (
                <tr key={c.category}><th scope="row">{c.category}</th><td className="num">{c.passed}</td><td className="num">{c.total}</td><td className="num">{fmtPercent(c.percent)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="grain">Categories are derived by app rules from check names; they are not a benchmark mapping.</p>
        </>
      )}
    </section>
  );
}

export function MachinePage() {
  const api = usePolicyApi();
  const [params] = useSearchParams();
  const id = params.get("id") ?? "";
  const state = useAsync((s) => api.machineDetail(id, s), [id]);
  return (
    <div className="detail-page">
      <p><Link to="/explorer?tab=machines">← Back to machines</Link></p>
      {state.status === "loading" && <Loading what="machine" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && (
        <>
          <p className="eyebrow">{state.data.machine.kind === "ArcMachine" ? "Arc machine" : "Azure VM"}</p>
          <h2>{state.data.machine.name}</h2>
          <dl className="facts-grid">
            <dt>Subscription</dt><dd>{state.data.machine.subscriptionId}</dd>
            <dt>Resource group</dt><dd>{state.data.machine.resourceGroup ?? "unknown"}</dd>
            <dt>Location</dt><dd>{state.data.machine.location ?? "unknown"}</dd>
            <dt>Operating system</dt><dd>{[state.data.machine.osName, state.data.machine.osBuild].filter(Boolean).join(" ") || "unknown"}</dd>
            <dt>Eligibility</dt><dd>{state.data.machine.eligibility ?? "unknown"}</dd>
            <dt>Snapshot</dt><dd>{formatWhen(state.data.snapshotAt)}</dd>
          </dl>
          {state.data.families.map((f) => <FamilySection key={f.family} f={f} />)}
          <section className="panel" aria-label="Azure Policy states">
            <h3>Azure Policy states for this machine</h3>
            <p className="grain">{state.data.policy.tally.compliant} compliant · {state.data.policy.tally.nonCompliant} non-compliant · {state.data.policy.tally.exempt} exempt · {state.data.policy.tally.other} not assessed</p>
            {state.data.policy.states.length === 0 ? (
              <Empty>No Azure Policy evaluations for this machine.</Empty>
            ) : (
              <table className="data-table">
                <caption className="sr-only">Azure Policy states</caption>
                <thead><tr><th scope="col">Policy</th><th scope="col">Initiative</th><th scope="col">State</th><th scope="col">Effect</th></tr></thead>
                <tbody>
                  {state.data.policy.states.map((s, i) => (
                    <tr key={`${s.policy}-${i}`}><th scope="row">{s.policy}</th><td>{s.initiative}</td><td>{s.state}</td><td>{s.effect}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="panel" aria-label="History">
            <h3>Baseline history</h3>
            <p className="grain">{state.data.historyNote}</p>
            {state.data.history.length > 0 && (
              <table className="data-table">
                <caption className="sr-only">History</caption>
                <thead><tr><th scope="col">Snapshot</th><th scope="col">Family</th><th scope="col">Evidence</th><th scope="col">Reported state</th><th scope="col">Meets baseline</th></tr></thead>
                <tbody>
                  {state.data.history.map((h) => (
                    <tr key={`${h.snapshotAt}-${h.family}`}><th scope="row">{formatWhen(h.snapshotAt)}</th><td>{h.family}</td><td>{h.evidenceQuality}</td><td>{h.reportedState ?? "not assessed"}</td><td>{h.green ? "yes" : "no"}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
