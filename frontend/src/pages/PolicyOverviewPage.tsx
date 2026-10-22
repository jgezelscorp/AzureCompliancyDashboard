import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDomainApi } from "../api/domainContext";
import type { DomainOverview, Frameworks } from "../api/domainTypes";
import { usePolicyApi } from "../api/policyContext";
import type { Breakdown, BreakdownRow, Filters, PolicyOverview } from "../api/policyTypes";
import { BarLegend, RankedBars, StackedBar, TrendChart } from "../components/charts";
import { Empty, ErrorState, Loading } from "../components/common";
import { ByDomainPanel, DomainQualityTile, FrameworksPanel } from "../components/DomainPanels";
import { KpiTile } from "../components/KpiTile";
import { useAsync, type AsyncState } from "../hooks/useAsync";
import { confidenceLabel, downloadCsv, overviewDomainCsv } from "../lib/domainFormat";
import { drillSearch, fmtPercent, formatWhen, rowDrill, shortType, toCsv } from "../lib/policyFormat";

const DIMENSIONS: { id: string; label: string }[] = [
  { id: "initiative", label: "Initiative / standard" },
  { id: "subscription", label: "Subscription" },
  { id: "resourceGroup", label: "Resource group" },
  { id: "resourceType", label: "Resource type" },
  { id: "location", label: "Location" },
  { id: "category", label: "Policy category" },
  { id: "tag:owner", label: "Tag: owner" },
  { id: "tag:environment", label: "Tag: environment" },
];

function Panel<T>({
  title,
  what,
  state,
  children,
  aside,
}: {
  title: string;
  what: string;
  state: AsyncState<T> & { reload: () => void };
  children: (data: T) => ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="panel" aria-label={title}>
      <div className="panel-head">
        <h2>{title}</h2>
        {aside}
      </div>
      {state.status === "loading" && <Loading what={what} />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && children(state.data)}
    </section>
  );
}

function BreakdownTable({ data, dim }: { data: Breakdown; dim: string }) {
  if (data.rows.length === 0) return <Empty>No evaluations in scope for this dimension.</Empty>;
  return (
    <>
      <BarLegend />
      <table className="data-table">
        <caption className="sr-only">Compliance by {dim}; {data.grain}</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">Compliance</th>
            <th scope="col" className="num">% compliant</th>
            <th scope="col" className="num">Non-compliant</th>
            <th scope="col" className="num">Evaluations</th>
            <th scope="col" className="num">Resources failing</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r: BreakdownRow) => {
            const drill = rowDrill(dim, r);
            return (
              <tr key={r.key}>
                <th scope="row">
                  {drill ? (
                    <Link to={`/explorer${drillSearch({ tab: "states", params: drill })}`}>{dim === "resourceType" ? shortType(r.label) : r.label}</Link>
                  ) : (
                    r.label
                  )}
                </th>
                <td><StackedBar row={r} /></td>
                <td className="num">{fmtPercent(r.percent)}</td>
                <td className="num">{r.nonCompliant.toLocaleString("en")}</td>
                <td className="num">{r.evaluations.toLocaleString("en")}</td>
                <td className="num">{r.nonCompliantResources.toLocaleString("en")} / {r.resources.toLocaleString("en")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="grain">{data.grain}. {data.formula}.</p>
    </>
  );
}

function BreakdownPanel({ filters }: { filters: Filters }) {
  const api = usePolicyApi();
  const [dim, setDim] = useState("initiative");
  const state = useAsync((s) => api.breakdown(dim, filters, { limit: 15 }, s), [dim, JSON.stringify(filters)]);
  return (
    <Panel
      title="Compliance breakdown"
      what="breakdown"
      state={state}
      aside={
        <label className="select-label">
          Break down by{" "}
          <select value={dim} onChange={(e) => setDim(e.target.value)}>
            {DIMENSIONS.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
        </label>
      }
    >
      {(data) => <BreakdownTable data={data} dim={dim} />}
    </Panel>
  );
}

function TopPoliciesPanel({ filters }: { filters: Filters }) {
  const api = usePolicyApi();
  const state = useAsync((s) => api.topPolicies(filters, 10, s), [JSON.stringify(filters)]);
  return (
    <Panel title="Top 10 failing policies" what="top policies" state={state}>
      {(data) =>
        data.rows.length === 0 ? (
          <Empty>No non-compliant policy evaluations in scope.</Empty>
        ) : (
          <>
            <RankedBars
              caption="Top failing policies by affected resources"
              items={data.rows.map((p) => ({
                key: p.definition,
                value: p.affectedResources,
                label: (
                  <Link to={`/explorer${drillSearch({ tab: "states", params: { definition: [p.definition], state: ["NonCompliant"] } })}`}>{p.name}</Link>
                ),
                detail: `resources · ${p.category} · ${p.effect}${p.severity && p.severity !== "none" ? ` · severity ${p.severity}` : ""}${p.domain ? ` · domain ${p.domain} (${confidenceLabel(p.domainConfidence)})` : ""}`,
              }))}
            />
            <p className="grain">{data.grain}</p>
          </>
        )
      }
    </Panel>
  );
}

function RiskiestPanel({ dim, title }: { dim: string; title: string }) {
  const api = usePolicyApi();
  const state = useAsync((s) => api.breakdown(dim, {}, { limit: 10, sort: "nonCompliantResources", desc: true }, s), [dim]);
  return (
    <Panel title={title} what={title} state={state}>
      {(data) => {
        const rows = data.rows.filter((r) => r.nonCompliantResources > 0);
        if (rows.length === 0) return <Empty>No non-compliant resources in this grouping.</Empty>;
        return (
          <RankedBars
            caption={title}
            items={rows.map((r) => {
              const drill = rowDrill(dim, r);
              const label = dim === "resourceType" ? shortType(r.label) : r.label;
              return {
                key: r.key,
                value: r.nonCompliantResources,
                label: drill ? <Link to={`/explorer${drillSearch({ tab: "resources", params: { ...drill, state: ["NonCompliant"] } })}`}>{label}</Link> : label,
                detail: `of ${r.resources} resources · ${fmtPercent(r.percent)}`,
              };
            })}
          />
        );
      }}
    </Panel>
  );
}

function TrendPanel() {
  const api = usePolicyApi();
  const state = useAsync((s) => api.trend(s), []);
  return (
    <Panel title="Compliance trend" what="trend" state={state}>
      {(t) => (
        <>
          <p className="grain">{t.note}</p>
          {t.taxonomyChanged && (
            <p role="status" className="state state-stale">
              <span className="badge tone-warn"><span aria-hidden="true">▲</span> Taxonomy changed</span>{" "}
              {t.taxonomyNote ?? "Domain breakdowns across samples with different taxonomy versions are not strictly comparable."}
              {t.taxonomyVersions && t.taxonomyVersions.length > 0 ? ` Versions in this window: ${t.taxonomyVersions.join(", ")}.` : ""}
            </p>
          )}
          <TrendChart points={t.points} />
          <details>
            <summary>Show the numbers</summary>
            <table className="data-table">
              <caption className="sr-only">Trend samples; {t.grain}</caption>
              <thead>
                <tr><th scope="col">Snapshot</th><th scope="col" className="num">% compliant</th><th scope="col" className="num">Non-compliant</th><th scope="col" className="num">New / recovered</th><th scope="col">Gap before</th></tr>
              </thead>
              <tbody>
                {t.points.map((p) => (
                  <tr key={p.runId}>
                    <th scope="row">{formatWhen(p.at)}</th>
                    <td className="num">{fmtPercent(p.percent)}</td>
                    <td className="num">{p.nonCompliant}</td>
                    <td className="num">+{p.newNonCompliant} / {p.recoveries}</td>
                    <td>{p.gapBefore ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="grain">{t.gapNote}</p>
          </details>
        </>
      )}
    </Panel>
  );
}

function ExemptionsPanel() {
  const api = usePolicyApi();
  const state = useAsync((s) => api.exemptions("all", s), []);
  return (
    <Panel title="Exemption expiry" what="exemptions" state={state}>
      {(e) => {
        const b = e.buckets;
        const items = [
          { key: "expired", label: "Already expired", value: b.expired },
          { key: "30", label: "Expire in under 30 days", value: b.expiring30 },
          { key: "60", label: "Expire in 30 to 59 days", value: b.expiring60 },
          { key: "90", label: "Expire in 60 to 89 days", value: b.expiring90 },
          { key: "none", label: "No expiry set", value: b.noExpiry },
        ];
        if (e.total === 0) return <Empty>No policy exemptions exist in scope.</Empty>;
        return (
          <>
            <p className="grain">{e.total} exemptions in scope ({e.note})</p>
            <RankedBars caption="Exemptions by time to expiry" items={items} />
            <table className="data-table">
              <caption className="sr-only">Exemptions</caption>
              <thead><tr><th scope="col">Exemption</th><th scope="col">Category</th><th scope="col">Expires</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {e.items.slice(0, 10).map((x) => (
                  <tr key={x.id}>
                    <th scope="row">{x.name}</th>
                    <td>{x.category}</td>
                    <td>{x.expiresOn ? `${formatWhen(x.expiresOn)}${x.daysToExpiry !== null ? ` (${x.daysToExpiry} d)` : ""}` : "no expiry"}</td>
                    <td>{x.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        );
      }}
    </Panel>
  );
}

function QualityPanel() {
  const api = usePolicyApi();
  const state = useAsync((s) => api.quality(s), []);
  return (
    <Panel title="Data quality: what we cannot see" what="data quality" state={state}>
      {(q) => (
        <>
          <ul className="facts">
            <li>Evidence freshness: {q.freshness.fresh} of {q.freshness.evaluations} evaluations are newer than {q.freshness.thresholdHours} h (newest {formatWhen(q.freshness.newest)}, oldest {formatWhen(q.freshness.oldest)}).</li>
            <li>Inventory: {q.inventory.resources} resources visible, {q.inventory.withEvaluations} with policy evaluations, {q.inventory.withoutEvaluations} without any (not part of any denominator). {q.inventory.note}</li>
            <li>Metadata: {q.metadata.definitionsWithSeverity} of {q.metadata.definitionsResolved} resolved definitions carry severity; {q.metadata.evaluationsUncategorized} of {q.metadata.evaluations} evaluations have no category. {q.metadata.note}</li>
            <li>Defender for Cloud: {q.defender.available ? "available (shown separately)" : "not available for this scope; nothing is estimated"}.</li>
            <li>{q.cisNotAssessed}</li>
            {q.limits.map((l) => <li key={l}>{l}</li>)}
          </ul>
          {q.inventory.withoutEvaluationsTopTypes.length > 0 && (
            <p className="grain">Most common unevaluated types: {q.inventory.withoutEvaluationsTopTypes.map((t) => `${shortType(t.type)} (${t.count})`).join(", ")}.</p>
          )}
        </>
      )}
    </Panel>
  );
}

function MachinesPanel() {
  const api = usePolicyApi();
  const state = useAsync((s) => api.machineCoverage(s), []);
  return (
    <Panel title="Machine Configuration baseline" what="machine coverage" state={state}>
      {(m) =>
        m.groups.length === 0 ? (
          <Empty>No machine evidence in scope; baseline pass rate is not assessed.</Empty>
        ) : (
          <>
            <table className="data-table">
              <caption className="sr-only">Machine coverage and check pass rate; separate metrics</caption>
              <thead>
                <tr>
                  <th scope="col">Group</th>
                  <th scope="col" className="num">Machines</th>
                  <th scope="col" className="num">Assigned / eligible</th>
                  <th scope="col" className="num">Fresh report</th>
                  <th scope="col" className="num">Check pass rate</th>
                  <th scope="col" className="num">Policy compliance</th>
                </tr>
              </thead>
              <tbody>
                {m.groups.map((g) => (
                  <tr key={g.label}>
                    <th scope="row">{g.label}</th>
                    <td className="num">{g.machines}</td>
                    <td className="num">{g.coverage.assigned} / {g.coverage.eligible}</td>
                    <td className="num">{g.coverage.freshReport} ({fmtPercent(g.coverage.freshReportPercent)})</td>
                    <td className="num">{fmtPercent(g.checkPassRate.percent)} ({g.checkPassRate.passed}/{g.checkPassRate.total} checks)</td>
                    <td className="num">{fmtPercent(g.policyCompliance.percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="grain">{m.note}</p>
            <p><Link to="/ciso">Open the machine baseline view</Link></p>
          </>
        )
      }
    </Panel>
  );
}

export function exportOverviewCsv(
  o: PolicyOverview,
  domains?: { overview: DomainOverview | null; frameworks: Frameworks | null; selected: string[] },
): string {
  const rows: unknown[][] = [
    ["Azure Policy estate overview (reporting aid, not a certification)"],
    ["Snapshot", o.snapshotAt ?? "unknown"],
    ["Scope", `${o.scope.authorizedSubscriptions} authorized of ${o.scope.onboardedSubscriptions} onboarded subscriptions${o.scope.partial ? " (partial)" : ""}`],
    [],
    ["KPI", "Value", "Unit", "Numerator", "Denominator", "Grain", "Delta vs previous", "Formula"],
    ...o.kpis.map((k) => [k.label, k.value ?? "n/a", k.unit, k.numerator ?? "", k.denominator ?? "", k.grain, k.delta ?? "", k.formula]),
    [],
    ["Summary"],
    ...o.summary.map((s) => [s]),
    [],
    [o.sampleNote],
    ...o.labels.map((l) => [l]),
  ];
  if (domains?.overview) rows.push(...overviewDomainCsv(domains.overview, domains.frameworks, domains.selected));
  return toCsv(rows);
}

export function PolicyOverviewPage() {
  const api = usePolicyApi();
  const domainApi = useDomainApi();
  const [params, setParams] = useSearchParams();
  const selected = params.getAll("domain").filter(Boolean);
  const filters: Filters = selected.length ? { domain: selected } : {};
  const key = JSON.stringify(filters);
  const state = useAsync((s) => api.overview(filters, s), [key]);
  const dom = useAsync((s) => domainApi.overview(filters, s), [key]);
  const fw = useAsync((s) => domainApi.frameworks(filters, s), [key]);
  const setDomains = (next: string[]) => {
    const q = new URLSearchParams(params);
    q.delete("domain");
    for (const d of next) q.append("domain", d);
    setParams(q);
  };
  const exportCsv = (o: PolicyOverview) =>
    downloadCsv(
      "policy-overview.csv",
      exportOverviewCsv(o, {
        overview: dom.status === "ready" ? dom.data : null,
        frameworks: fw.status === "ready" ? fw.data : null,
        selected,
      }),
    );
  return (
    <div className="overview">
      <div className="page-head">
        <div>
          <p className="eyebrow">Azure Policy estate</p>
          <h2>CISO overview</h2>
        </div>
        {state.status === "ready" && (
          <div className="page-actions no-print">
            <button type="button" className="btn" onClick={() => exportCsv(state.data)}>Export CSV</button>
            <button type="button" className="btn" onClick={() => window.print()}>Print / save as PDF</button>
          </div>
        )}
      </div>
      {dom.status === "ready" && (
        <form className="filter-bar no-print" role="search" aria-label="Domain filter" onSubmit={(e) => e.preventDefault()}>
          <label>
            Security domain
            <select value="" onChange={(e) => e.target.value && !selected.includes(e.target.value) && setDomains([...selected, e.target.value])}>
              <option value="">Add…</option>
              {dom.data.domains.map((d) => <option key={d.domain} value={d.domain}>{d.label}</option>)}
            </select>
          </label>
          {selected.length > 0 && (
            <ul className="chips" aria-label="Active domain filters">
              {selected.map((d) => (
                <li key={d}>
                  <button type="button" className="chip" aria-label={`Remove domain filter ${d}`} onClick={() => setDomains(selected.filter((x) => x !== d))}>domain: {d} ✕</button>
                </li>
              ))}
              <li><button type="button" className="link-btn" onClick={() => setDomains([])}>Clear all</button></li>
            </ul>
          )}
        </form>
      )}
      {selected.length > 0 && (
        <p className="grain">Domain filter active: {selected.join(", ")}. Policy panels, the domain panels and the CSV export all use it.</p>
      )}
      {state.status === "loading" && <Loading what="policy overview" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && <OverviewBody o={state.data} />}
      <TrendPanel />
      <ByDomainPanel state={dom} selected={selected} />
      <div className="grid-2">
        <FrameworksPanel state={fw} />
        <DomainQualityTile state={dom} />
      </div>
      <BreakdownPanel filters={filters} />
      <div className="grid-2">
        <TopPoliciesPanel filters={filters} />
        <ExemptionsPanel />
      </div>
      <div className="grid-3">
        <RiskiestPanel dim="resourceGroup" title="Riskiest resource groups" />
        <RiskiestPanel dim="tag:owner" title="Riskiest owners (owner tag)" />
        <RiskiestPanel dim="resourceType" title="Riskiest resource types" />
      </div>
      <MachinesPanel />
      <QualityPanel />
    </div>
  );
}

function OverviewBody({ o }: { o: PolicyOverview }) {
  return (
    <>
      <p className="scope-line">
        Snapshot {formatWhen(o.snapshotAt)} · {o.scope.authorizedSubscriptions} of {o.scope.onboardedSubscriptions} onboarded subscriptions visible
        {o.scope.partial ? " (partial: some scopes are hidden by your Azure RBAC access)" : ""} · {o.sampleNote}
      </p>
      {o.snapshotAt === null && <Empty>No policy data has been collected for your scope yet. Nothing is shown as compliant.</Empty>}
      <section className="panel" aria-label="Executive summary">
        <h2>Executive summary (facts only)</h2>
        <ul className="facts">{o.summary.map((s) => <li key={s}>{s}</li>)}</ul>
      </section>
      <section aria-label="Headline KPIs" className="kpi-grid">
        {o.kpis.map((k) => <KpiTile key={k.id} kpi={k} snapshotAt={o.snapshotAt} />)}
      </section>
      <ul className="labels">{o.labels.map((l) => <li key={l}>{l}</li>)}</ul>
    </>
  );
}
