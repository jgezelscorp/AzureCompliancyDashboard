import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMetricsApi } from "../api/context";
import { usePolicyApi } from "../api/policyContext";
import { FILTER_KEYS, type BreakdownRow, type Filters, type ResourceRow, type StateRow, type TopPolicy } from "../api/policyTypes";
import type { MachineRow, MetricFamily } from "../api/types";
import { StackedBar } from "../components/charts";
import { ErrorState, Loading } from "../components/common";
import { DataGrid, type Column } from "../components/DataGrid";
import { FilterBar, activeCount } from "../components/FilterBar";
import { useAsync } from "../hooks/useAsync";
import { FAMILIES, FAMILY_LABEL } from "../lib/format";
import { drillSearch, filtersFromSearch, fmtPercent, formatWhen, rowDrill, shortType } from "../lib/policyFormat";

const TABS = [
  { id: "states", label: "Policy states" },
  { id: "resources", label: "Resources" },
  { id: "policies", label: "Policies" },
  { id: "initiatives", label: "Initiatives" },
  { id: "machines", label: "Machines" },
] as const;
type TabId = (typeof TABS)[number]["id"];
const PAGE = 50;

interface View {
  tab: TabId;
  filters: Filters;
  sort: string | undefined;
  desc: boolean;
  offset: number;
}

function useView(): [View, (patch: Partial<View>) => void] {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab = (TABS.find((t) => t.id === tabParam)?.id ?? "states") as TabId;
  const view: View = {
    tab,
    filters: filtersFromSearch(params),
    sort: params.get("sort") ?? undefined,
    desc: params.get("desc") !== "false",
    offset: Math.max(0, Number(params.get("offset")) || 0),
  };
  const update = useCallback(
    (patch: Partial<View>) => {
      const next = { ...view, ...patch };
      // a changed tab, filter or sort restarts paging unless offset is set explicitly
      if (patch.offset === undefined) next.offset = 0;
      const q = new URLSearchParams();
      q.set("tab", next.tab);
      for (const k of FILTER_KEYS) for (const v of next.filters[k] ?? []) q.append(k, v);
      if (next.sort) q.set("sort", next.sort);
      if (next.sort && !next.desc) q.set("desc", "false");
      if (next.offset) q.set("offset", String(next.offset));
      setParams(q, { replace: false });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params],
  );
  return [view, update];
}

const stateTone = (s: string) => (s === "NonCompliant" ? "bad" : s === "Compliant" ? "good" : "nodata");

function StatesTab({ view, update }: { view: View; update: (p: Partial<View>) => void }) {
  const api = usePolicyApi();
  const state = useAsync((s) => api.states(view.filters, { limit: PAGE, offset: view.offset, sort: view.sort ?? "state", desc: view.desc }, s), [JSON.stringify(view)]);
  const cols: Column<StateRow>[] = [
    { id: "res", header: "Resource", sort: "resource", rowHeader: true, render: (r) => <Link to={`/resource?id=${encodeURIComponent(r.resourceId)}`}>{r.resourceName}</Link> },
    { id: "type", header: "Type", sort: "type", render: (r) => shortType(r.resourceType) },
    { id: "rg", header: "Resource group", render: (r) => r.resourceGroup || "(subscription)" },
    { id: "policy", header: "Policy", sort: "policy", render: (r) => r.policy },
    { id: "init", header: "Initiative", sort: "initiative", render: (r) => r.initiative },
    { id: "state", header: "State", sort: "state", render: (r) => <span className={`badge tone-${stateTone(r.state)}`}>{r.state}</span> },
    { id: "effect", header: "Effect", sort: "effect", render: (r) => r.effect },
    { id: "cat", header: "Category", sort: "category", render: (r) => r.category },
    { id: "ts", header: "Evaluated", sort: "evaluated", render: (r) => formatWhen(r.evaluatedAt) },
  ];
  if (state.status === "loading") return <Loading what="policy states" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  const d = state.data;
  return (
    <>
      <p className="grain">
        {d.tally.evaluations.toLocaleString("en")} evaluations match · {d.tally.compliant} compliant · {d.tally.nonCompliant} non-compliant · {d.tally.exempt} exempt · {d.tally.other} not assessed · {fmtPercent(d.tally.percent)} compliant (excludes exempt and not assessed) · {d.tally.nonCompliantResources} of {d.tally.resources} resources failing. Grain: {d.grain}.
      </p>
      <DataGrid caption="Policy states" columns={cols} rows={d.rows} rowKey={(r) => `${r.resourceId}|${r.assignmentId}|${r.definition}`} sort={view.sort ?? "state"} desc={view.desc} onSort={(sort, desc) => update({ sort, desc })} total={d.total} offset={d.offset} limit={PAGE} onPage={(offset) => update({ offset })} />
    </>
  );
}

function ResourcesTab({ view, update }: { view: View; update: (p: Partial<View>) => void }) {
  const api = usePolicyApi();
  const state = useAsync((s) => api.resources(view.filters, { limit: PAGE, offset: view.offset, sort: view.sort ?? "nonCompliant", desc: view.desc }, s), [JSON.stringify(view)]);
  const cols: Column<ResourceRow>[] = [
    { id: "name", header: "Resource", sort: "name", rowHeader: true, render: (r) => <Link to={`/resource?id=${encodeURIComponent(r.resourceId)}`}>{r.name}</Link> },
    { id: "type", header: "Type", sort: "type", render: (r) => shortType(r.resourceType) },
    { id: "rg", header: "Resource group", sort: "resourceGroup", render: (r) => r.resourceGroup || "(subscription)" },
    { id: "loc", header: "Location", render: (r) => r.location || "(global)" },
    { id: "owner", header: "Owner tag", render: (r) => r.tags.owner ?? r.tags.Owner ?? "(untagged)" },
    { id: "fail", header: "Failing policies", sort: "failingPolicies", numeric: true, render: (r) => r.failingPolicies },
    { id: "nc", header: "Non-compliant", sort: "nonCompliant", numeric: true, render: (r) => r.nonCompliant },
    { id: "ev", header: "Evaluations", sort: "evaluations", numeric: true, render: (r) => r.evaluations },
    { id: "ts", header: "Newest", sort: "newest", render: (r) => formatWhen(r.newestEvaluation) },
  ];
  if (state.status === "loading") return <Loading what="resources" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  const d = state.data;
  return (
    <>
      <p className="grain">{d.total.toLocaleString("en")} resources have evaluations matching the filters. Grain: {d.grain}.</p>
      <DataGrid caption="Resources" columns={cols} rows={d.rows} rowKey={(r) => r.resourceId} sort={view.sort ?? "nonCompliant"} desc={view.desc} onSort={(sort, desc) => update({ sort, desc })} total={d.total} offset={d.offset} limit={PAGE} onPage={(offset) => update({ offset })} />
    </>
  );
}

function PoliciesTab({ view }: { view: View }) {
  const api = usePolicyApi();
  const state = useAsync((s) => api.topPolicies(view.filters, 100, s), [JSON.stringify(view.filters)]);
  const cols: Column<TopPolicy>[] = [
    { id: "name", header: "Policy", rowHeader: true, render: (p) => <Link to={`/explorer${drillSearch({ tab: "states", params: { definition: [p.definition], state: ["NonCompliant"] } })}`}>{p.name}</Link> },
    { id: "cat", header: "Category", render: (p) => p.category },
    { id: "effect", header: "Effect", render: (p) => p.effect },
    { id: "sev", header: "Severity", render: (p) => (p.severity && p.severity !== "none" ? p.severity : "not in metadata") },
    { id: "res", header: "Affected resources", numeric: true, render: (p) => p.affectedResources },
    { id: "nc", header: "Non-compliant evaluations", numeric: true, render: (p) => p.nonCompliant },
    { id: "init", header: "Initiatives", render: (p) => p.initiatives.join(", ") },
  ];
  if (state.status === "loading") return <Loading what="policies" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  const rows = state.data.rows;
  return (
    <>
      <p className="grain">Failing policy definitions, ranked by affected resources (up to 100). Grain: {state.data.grain}.</p>
      <DataGrid caption="Failing policies" columns={cols} rows={rows} rowKey={(p) => p.definition} total={rows.length} offset={0} limit={Math.max(rows.length, 1)} onPage={() => undefined} />
    </>
  );
}

function InitiativesTab({ view, update }: { view: View; update: (p: Partial<View>) => void }) {
  const api = usePolicyApi();
  const state = useAsync((s) => api.breakdown("initiative", view.filters, { limit: PAGE, offset: view.offset, sort: view.sort ?? "nonCompliant", desc: view.desc }, s), [JSON.stringify(view)]);
  const cols: Column<BreakdownRow>[] = [
    {
      id: "name",
      header: "Initiative / standard",
      sort: "label",
      rowHeader: true,
      render: (r) => {
        const drill = rowDrill("initiative", r);
        return drill ? <Link to={`/explorer${drillSearch({ tab: "states", params: drill })}`}>{r.label}</Link> : r.label;
      },
    },
    { id: "bar", header: "Compliance", render: (r) => <StackedBar row={r} /> },
    { id: "pct", header: "% compliant", sort: "percent", numeric: true, render: (r) => fmtPercent(r.percent) },
    { id: "nc", header: "Non-compliant", sort: "nonCompliant", numeric: true, render: (r) => r.nonCompliant },
    { id: "ev", header: "Evaluations", sort: "evaluations", numeric: true, render: (r) => r.evaluations },
    { id: "res", header: "Failing resources", sort: "nonCompliantResources", numeric: true, render: (r) => `${r.nonCompliantResources} / ${r.resources}` },
  ];
  if (state.status === "loading") return <Loading what="initiatives" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  const d = state.data;
  return (
    <>
      <p className="grain">{d.grain}. {d.formula}.</p>
      <DataGrid caption="Initiatives" columns={cols} rows={d.rows} rowKey={(r) => r.key} sort={view.sort ?? "nonCompliant"} desc={view.desc} onSort={(sort, desc) => update({ sort, desc })} total={d.total} offset={view.offset} limit={PAGE} onPage={(offset) => update({ offset })} />
    </>
  );
}

function MachinesTab() {
  const api = useMetricsApi();
  const [family, setFamily] = useState<MetricFamily>("AzureWindowsBaseline");
  const state = useAsync((s) => api.machines(family, s), [family]);
  const cols: Column<MachineRow>[] = [
    { id: "name", header: "Machine", rowHeader: true, render: (m) => <Link to={`/machine?id=${encodeURIComponent(m.machineId)}`}>{m.name}</Link> },
    { id: "kind", header: "Kind", render: (m) => (m.kind === "ArcMachine" ? "Arc machine" : "Azure VM") },
    { id: "eq", header: "Evidence", render: (m) => m.evidenceQuality },
    { id: "rs", header: "Reported state", render: (m) => m.reportedState ?? "not assessed" },
    { id: "g", header: "Meets baseline", render: (m) => (m.green ? "yes" : "no") },
  ];
  return (
    <>
      <label className="select-label">Baseline family{" "}
        <select value={family} onChange={(e) => setFamily(e.target.value as MetricFamily)}>
          {FAMILIES.map((f) => <option key={f} value={f}>{FAMILY_LABEL[f]}</option>)}
        </select>
      </label>
      {state.status === "loading" && <Loading what="machines" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && (
        <>
          {family === "CISWindowsSecurityBaseline" && state.data.machines.every((m) => m.evidenceQuality === "MissingAssignment") && (
            <p className="state state-empty">No CIS assignment exists for these machines: CIS results are not assessed.</p>
          )}
          <DataGrid caption="Machines" columns={cols} rows={state.data.machines} rowKey={(m) => m.machineId} total={state.data.total} offset={0} limit={Math.max(state.data.machines.length, 1)} onPage={() => undefined} />
        </>
      )}
    </>
  );
}

export function ExplorerPage() {
  const api = usePolicyApi();
  const [view, update] = useView();
  const options = useAsync((s) => api.filters(s), []);
  useEffect(() => {
    document.title = "Explorer · Azure Compliancy Dashboard";
  }, []);
  const filterable = view.tab !== "machines";
  return (
    <div className="explorer">
      <p className="eyebrow">Technical explorer</p>
      <h2>Explore policy evidence</h2>
      <div role="tablist" aria-label="Explorer sections" className="tabs">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={view.tab === t.id} aria-controls="explorer-panel" className="tab" onClick={() => update({ tab: t.id, sort: undefined, desc: true })}>
            {t.label}
          </button>
        ))}
      </div>
      {filterable && (
        <FilterBar filters={view.filters} options={options.status === "ready" ? options.data : null} onChange={(filters) => update({ filters })} />
      )}
      {filterable && activeCount(view.filters) > 0 && <p className="grain">Filters apply to every number below and are kept in the URL, so this view can be shared as a link (the recipient still sees only what their own Azure RBAC access allows).</p>}
      <section id="explorer-panel" role="tabpanel" aria-labelledby={`tab-${view.tab}`} className="panel">
        {view.tab === "states" && <StatesTab view={view} update={update} />}
        {view.tab === "resources" && <ResourcesTab view={view} update={update} />}
        {view.tab === "policies" && <PoliciesTab view={view} />}
        {view.tab === "initiatives" && <InitiativesTab view={view} update={update} />}
        {view.tab === "machines" && <MachinesTab />}
      </section>
      <p><Link to="/technical">Open the machine baseline checks view</Link></p>
    </div>
  );
}
