import { Link, useSearchParams } from "react-router-dom";
import { usePolicyApi } from "../api/policyContext";
import { Empty, ErrorState, Loading } from "../components/common";
import { useAsync } from "../hooks/useAsync";
import { fmtPercent, formatWhen, shortType } from "../lib/policyFormat";

export function ResourcePage() {
  const api = usePolicyApi();
  const [params] = useSearchParams();
  const id = params.get("id") ?? "";
  const state = useAsync((s) => api.resource(id, s), [id]);
  return (
    <div className="detail-page">
      <p><Link to="/explorer?tab=resources">← Back to resources</Link></p>
      {state.status === "loading" && <Loading what="resource" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && (
        <>
          <p className="eyebrow">{shortType(state.data.resourceType)}</p>
          <h2>{state.data.name}</h2>
          <dl className="facts-grid">
            <dt>Subscription</dt><dd>{state.data.subscriptionId}</dd>
            <dt>Resource group</dt><dd>{state.data.resourceGroup || "(subscription scope)"}</dd>
            <dt>Location</dt><dd>{state.data.location || "(global)"}</dd>
            <dt>Tags</dt>
            <dd>{Object.keys(state.data.tags).length ? Object.entries(state.data.tags).map(([k, v]) => `${k}=${v}`).join(", ") : "none collected"}</dd>
            <dt>Evaluations</dt>
            <dd>{state.data.tally.compliant} compliant · {state.data.tally.nonCompliant} non-compliant · {state.data.tally.exempt} exempt · {state.data.tally.other} not assessed · {fmtPercent(state.data.tally.percent)} compliant</dd>
            <dt>Snapshot</dt><dd>{formatWhen(state.data.snapshotAt)}</dd>
          </dl>
          <section className="panel" aria-label="Policy states">
            <h3>Policy states for this resource</h3>
            {state.data.states.length === 0 ? (
              <Empty>No policy evaluations for this resource.</Empty>
            ) : (
              <table className="data-table">
                <caption className="sr-only">Policy states</caption>
                <thead><tr><th scope="col">Policy</th><th scope="col">Initiative</th><th scope="col">State</th><th scope="col">Effect</th><th scope="col">Evaluated</th></tr></thead>
                <tbody>
                  {state.data.states.map((s, i) => (
                    <tr key={`${s.definition}-${s.assignmentId}-${i}`}>
                      <th scope="row">{s.policy}</th>
                      <td>{s.initiative}</td>
                      <td>{s.state}</td>
                      <td>{s.effect}</td>
                      <td>{formatWhen(s.evaluatedAt)}</td>
                    </tr>
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
