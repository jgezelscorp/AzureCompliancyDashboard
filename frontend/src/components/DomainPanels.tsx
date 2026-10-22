import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { CONFIDENCES, type DomainOverview, type Frameworks, type ProvenanceMix } from "../api/domainTypes";
import { Empty, ErrorState, Loading } from "./common";
import { ProvenanceBadge } from "./ProvenanceBadge";
import type { AsyncState } from "../hooks/useAsync";
import { DISCLAIMER_FALLBACK, familyLabel, visibleDomains } from "../lib/domainFormat";
import { drillSearch, fmtPercent } from "../lib/policyFormat";

type Loadable<T> = AsyncState<T> & { reload: () => void };

function Shell<T>({ title, what, state, children }: { title: string; what: string; state: Loadable<T>; children: (d: T) => ReactNode }) {
  return (
    <section className="panel" aria-label={title}>
      <div className="panel-head">
        <h2>{title}</h2>
      </div>
      {state.status === "loading" && <Loading what={what} />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && children(state.data)}
    </section>
  );
}

export function ByDomainPanel({ state, selected }: { state: Loadable<DomainOverview>; selected: string[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <Shell title="By security domain" what="security domains" state={state}>
      {(o) => {
        const rows = visibleDomains(o, selected);
        if (rows.length === 0) return <Empty>No security domain matches the active domain filter.</Empty>;
        return (
          <>
            <p className="grain">
              Policy compliance % and machine check pass rate are shown side by side and are never merged into one score. Each policy or check counts once, in one domain.
            </p>
            <div className="table-scroll" tabIndex={0} role="region" aria-label="Security domains (scrollable)">
              <table className="data-table">
                <caption className="sr-only">Security domains: Azure Policy compliance and machine check pass rate are separate metrics</caption>
                <thead>
                  <tr>
                    <th scope="col">Domain</th>
                    <th scope="col" className="num">Policy compliance (evaluations)</th>
                    <th scope="col" className="num">Machine check pass rate (check results)</th>
                    <th scope="col">Drill through</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => {
                    const fams = Object.entries(d.machine);
                    return (
                      <tr key={d.domain}>
                        <th scope="row">{d.label}</th>
                        <td className="num">
                          {d.policy ? (
                            <>
                              {fmtPercent(d.policy.percent)}
                              <span className="muted"> {d.policy.compliant.toLocaleString("en")} of {(d.policy.compliant + d.policy.nonCompliant).toLocaleString("en")} counted · {d.policy.resources.toLocaleString("en")} resources</span>
                            </>
                          ) : (
                            <span className="muted">no policy evaluations</span>
                          )}
                        </td>
                        <td className="num">
                          {fams.length === 0 ? (
                            <span className="muted">no machine check results</span>
                          ) : (
                            fams.map(([fam, t]) => (
                              <div key={fam}>
                                {familyLabel(fam)}: {fmtPercent(t.percent)}
                                <span className="muted"> {t.passed.toLocaleString("en")} of {t.total.toLocaleString("en")} results · {t.checks} checks · {t.machines} machines</span>
                              </div>
                            ))
                          )}
                        </td>
                        <td>
                          <Link to={`/explorer${drillSearch({ tab: "states", params: { domain: [d.domain] } })}`} aria-label={`Policy states in ${d.label}`}>Policy states</Link>
                          {" · "}
                          <Link to={`/technical?domain=${encodeURIComponent(d.domain)}`} aria-label={`Machine checks in ${d.label}`}>Machine checks</Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="grain">Policy grain: {o.grain.policy}. Machine grain: {o.grain.machine}.</p>
            <button type="button" className="link-btn" aria-expanded={open} aria-controls={`${id}-p`} onClick={() => setOpen((v) => !v)}>
              How is this calculated?
            </button>
            {open && (
              <div id={`${id}-p`} className="popover" role="region" aria-label="How security domain figures are calculated">
                <p>A domain is an app-curated grouping (taxonomy v{o.taxonomyVersion}), not a benchmark mapping. Every policy definition and every check belongs to exactly one domain, so domain rows do not double count.</p>
                <dl>
                  <dt>Policy compliance</dt>
                  <dd>{o.grain.policy}. Snapshot {o.snapshotAt ?? "unknown"}.</dd>
                  <dt>Machine check pass rate</dt>
                  <dd>{o.grain.machine}. Snapshot {o.machineSnapshotAt ?? "unknown"}. Shown per baseline family, never merged.</dd>
                  <dt>Denominators</dt>
                  <dd>Printed in every row; exempt and not assessed items are excluded from policy %, stale or missing machine reports from the pass rate.</dd>
                </dl>
              </div>
            )}
          </>
        );
      }}
    </Shell>
  );
}

export function FrameworksPanel({ state }: { state: Loadable<Frameworks> }) {
  return (
    <Shell title="By framework (indicative)" what="framework families" state={state}>
      {(f) => {
        const families = f.frameworks.flatMap((fw) => fw.families.map((fam) => ({ fw, fam })));
        if (families.length === 0) return <Empty>No framework family has related policies or checks in scope.</Empty>;
        return (
          <>
            <p className="grain" role="note">
              <strong>Not additive.</strong> {f.note}
            </p>
            <div className="table-scroll" tabIndex={0} role="region" aria-label="Framework families (scrollable)">
              <table className="data-table">
                <caption className="sr-only">Distinct policies and checks per indicative framework family; rows overlap</caption>
                <thead>
                  <tr>
                    <th scope="col">Framework</th>
                    <th scope="col">Family</th>
                    <th scope="col" className="num">Distinct policies</th>
                    <th scope="col" className="num">Distinct checks</th>
                    <th scope="col" className="num">Policy % compliant</th>
                  </tr>
                </thead>
                <tbody>
                  {families.map(({ fw, fam }) => (
                    <tr key={`${fw.framework}/${fam.family}`}>
                      <th scope="row">{fw.label}</th>
                      <td>{fam.label}</td>
                      <td className="num">{fam.policies.toLocaleString("en")}</td>
                      <td className="num">{fam.checks.toLocaleString("en")}</td>
                      <td className="num">{fmtPercent(fam.percent)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="grain disclaimer">{f.disclaimer || DISCLAIMER_FALLBACK}</p>
          </>
        );
      }}
    </Shell>
  );
}

function MixLine({ title, m }: { title: string; m: ProvenanceMix }) {
  if (m.total === 0) return <li>{title}: nothing in scope.</li>;
  return (
    <li>
      <strong>{title}</strong> ({m.total.toLocaleString("en")} distinct): {fmtPercent(m.unmappedPercent)} unmapped · source {fmtPercent(m.sourcePercent)} · derived {fmtPercent(m.derivedPercent)} · override {fmtPercent(m.overridePercent)}
      <ul className="mix" aria-label={`${title} by provenance`}>
        {CONFIDENCES.map((c) => (
          <li key={c}>
            <ProvenanceBadge confidence={c} /> {m.byConfidence[c].toLocaleString("en")}
          </li>
        ))}
      </ul>
    </li>
  );
}

export function DomainQualityTile({ state }: { state: Loadable<DomainOverview> }) {
  return (
    <Shell title="Domain data quality" what="domain provenance" state={state}>
      {(o) => (
        <>
          <ul className="facts">
            <MixLine title="Policies" m={o.provenance.policies} />
            <MixLine title="Checks" m={o.provenance.checks} />
          </ul>
          <p className="grain">Unmapped items are counted in “Other”, never dropped. Derived and unmapped assignments should be reviewed before relying on a domain figure.</p>
          <p>
            <Link to="/explorer?tab=needs-category">Open the Needs-category queue</Link>
          </p>
        </>
      )}
    </Shell>
  );
}
