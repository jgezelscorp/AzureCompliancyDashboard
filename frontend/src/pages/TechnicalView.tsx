import { useSearchParams } from "react-router-dom";
import { useMetricsApi } from "../api/context";
import type {
  CategoryRow,
  CheckMachineRow,
  CheckRow,
  FamilyMetrics,
  MachineRow,
  MetricFamily,
} from "../api/types";
import { Empty, ErrorState, Loading, ToneBadge } from "../components/common";
import { ExportControls } from "../components/ExportControls";
import { EvidenceNotice } from "../components/EvidenceNotice";
import { FamilyMetricCards } from "../components/FamilyMetricCards";
import { Trend, seriesFrom } from "../components/Trend";
import { useAsync } from "../hooks/useAsync";
import {
  FAMILIES,
  FAMILY_LABEL,
  QUALITY_LABEL,
  formatPercent,
  formatTimestamp,
  qualityTone,
  shortId,
  toneFor,
} from "../lib/format";

function isFamily(v: string | null): v is MetricFamily {
  return v === "AzureWindowsBaseline" || v === "CISWindowsSecurityBaseline";
}

export function TechnicalView() {
  const api = useMetricsApi();
  const [params, setParams] = useSearchParams();
  const family: MetricFamily = isFamily(params.get("family"))
    ? (params.get("family") as MetricFamily)
    : "AzureWindowsBaseline";
  const scope = params.get("scope") ?? "";
  const category = params.get("category") ?? "";
  const check = params.get("check") ?? "";

  const update = (next: Record<string, string>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    setParams(p);
  };

  const overview = useAsync(
    async (signal) => {
      const [latest, scopes] = await Promise.all([api.latest(signal), api.scopes(signal)]);
      return { latest, scopes };
    },
    [api],
  );

  if (overview.status === "loading") return <Loading what="technical view" />;
  if (overview.status === "error") {
    return <ErrorState error={overview.error} onRetry={overview.reload} />;
  }
  const { latest, scopes } = overview.data;

  if (latest.snapshotAt === null) {
    return (
      <section aria-labelledby="tech-h">
        <h2 id="tech-h">Technical view</h2>
        <Empty>
          {latest.scope.onboardedSubscriptions === 0
            ? "No subscription is onboarded yet. Ask an administrator to register a scope."
            : "No collection has completed yet, so there is no evidence to show. No data is not compliance."}
        </Empty>
        <EvidenceNotice labels={latest.labels} />
      </section>
    );
  }

  const scopeRow = scopes.scopes.find((s) => s.subscriptionId === scope);
  const familyMetrics: FamilyMetrics | undefined = latest.families.find((f) => f.family === family);
  const shown: FamilyMetrics | undefined =
    scope && scopeRow && familyMetrics
      ? {
          ...familyMetrics,
          ...scopeRow.families.find((f) => f.family === family)!,
        }
      : familyMetrics;

  return (
    <section aria-labelledby="tech-h">
      <h2 id="tech-h">Technical view</h2>
      <p className="detail">
        Snapshot {formatTimestamp(latest.snapshotAt)}
        {latest.scope.partial && " · You can see only some onboarded scopes; figures cover those only."}
      </p>
      {latest.dataStale && (
        <p role="alert" className="state state-stale">
          The latest collection is older than {latest.freshnessHours ?? 24} hours. Values are shown
          as stale, never as healthy.
        </p>
      )}

      <div className="filters">
        <label>
          Scope{" "}
          <select
            value={scope}
            onChange={(e) => update({ scope: e.target.value, category: "", check: "" })}
          >
            <option value="">All authorized scopes</option>
            {scopes.scopes.map((s) => (
              <option key={s.subscriptionId} value={s.subscriptionId}>
                {s.subscriptionId} ({s.machineCount} machines)
              </option>
            ))}
          </select>
        </label>
        <div role="group" aria-label="Baseline">
          {FAMILIES.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={f === family}
              onClick={() => update({ family: f, category: "", check: "" })}
            >
              {FAMILY_LABEL[f]}
            </button>
          ))}
        </div>
      </div>

      <nav aria-label="Drill-down path" className="crumbs">
        <ol>
          <li>
            <button type="button" onClick={() => update({ scope: "", category: "", check: "" })}>
              {scope ? "All scopes" : "All scopes (current)"}
            </button>
          </li>
          {scope && (
            <li>
              <button type="button" onClick={() => update({ category: "", check: "" })}>
                Scope {scope.slice(0, 8)}
              </button>
            </li>
          )}
          <li>
            <button type="button" onClick={() => update({ category: "", check: "" })}>
              {FAMILY_LABEL[family]}
            </button>
          </li>
          {category && (
            <li>
              <button type="button" onClick={() => update({ check: "" })}>
                {category}
              </button>
            </li>
          )}
          {check && <li aria-current="page">{check}</li>}
        </ol>
      </nav>

      <h3>{FAMILY_LABEL[family]}</h3>
      {shown ? (
        <FamilyMetricCards metrics={shown} stale={latest.dataStale} />
      ) : (
        <Empty>No metrics for this baseline.</Empty>
      )}
      <EvidenceNotice labels={latest.labels} family={family} />
      <ExportControls
        options={(() => {
          const sub = scope ? { subscriptionId: scope } : {};
          return [
            { label: "Export checks CSV", request: { format: "csv", dataset: "checks", family, ...sub } },
            { label: "Export machines CSV", request: { format: "csv", dataset: "machines", family, ...sub } },
            { label: "Export technical PDF", request: { format: "pdf", template: "technical", family, ...sub } },
          ];
        })()}
      />
      <HistorySection family={family} />

      {!category && (
        <>
          <CategoryTable
            family={family}
            scope={scope}
            onOpen={(c) => update({ category: c, check: "" })}
          />
          <MachineTable family={family} scope={scope} />
        </>
      )}
      {category && !check && (
        <CheckTable
          family={family}
          category={category}
          scope={scope}
          onOpen={(c) => update({ check: c })}
        />
      )}
      {category && check && <CheckMachineTable family={family} checkKey={check} scope={scope} />}
    </section>
  );
}

function HistorySection({ family }: { family: MetricFamily }) {
  const api = useMetricsApi();
  const state = useAsync((s) => api.history(family, s), [api, family]);
  return (
    <section aria-labelledby="hist-h">
      <h3 id="hist-h">Trend</h3>
      {state.status === "loading" && <Loading what="history" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" && (
        <Trend
          series={seriesFrom(state.data.points, state.data.aggregatesIncluded)}
          samplingNote={state.data.samplingNote}
        />
      )}
    </section>
  );
}

function CategoryTable(props: {
  family: MetricFamily;
  scope: string;
  onOpen: (category: string) => void;
}) {
  const api = useMetricsApi();
  const state = useAsync(
    (s) => api.categories(props.family, props.scope || undefined, s),
    [api, props.family, props.scope],
  );
  return (
    <section aria-labelledby="cat-h">
      <h3 id="cat-h">Categories</h3>
      {state.status === "loading" && <Loading what="categories" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" &&
        (state.data.categories.length === 0 ? (
          <Empty>
            No check results from fresh reports for this baseline and scope. Stale or missing
            reports are not counted as passing.
          </Empty>
        ) : (
          <table>
            <caption className="sr-only">Check results by category</caption>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col">Checks</th>
                <th scope="col">Pass rate</th>
              </tr>
            </thead>
            <tbody>
              {state.data.categories.map((c: CategoryRow) => (
                <tr key={c.category}>
                  <th scope="row">
                    <button type="button" onClick={() => props.onOpen(c.category)}>
                      {c.category}
                    </button>
                  </th>
                  <td>{c.checks}</td>
                  <td>
                    {formatPercent(c.percent)} ({c.passed}/{c.total}){" "}
                    <ToneBadge tone={toneFor(c.percent, false)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </section>
  );
}

function CheckTable(props: {
  family: MetricFamily;
  category: string;
  scope: string;
  onOpen: (checkKey: string) => void;
}) {
  const api = useMetricsApi();
  const state = useAsync(
    (s) => api.checks(props.family, props.category, props.scope || undefined, s),
    [api, props.family, props.category, props.scope],
  );
  return (
    <section aria-labelledby="chk-h">
      <h3 id="chk-h">Checks in {props.category}</h3>
      {state.status === "loading" && <Loading what="checks" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" &&
        (state.data.checks.length === 0 ? (
          <Empty>No checks in this category.</Empty>
        ) : (
          <table>
            <caption className="sr-only">Checks with machine counts</caption>
            <thead>
              <tr>
                <th scope="col">Check</th>
                <th scope="col">Failing machines</th>
                <th scope="col">Passing machines</th>
              </tr>
            </thead>
            <tbody>
              {state.data.checks.map((c: CheckRow) => (
                <tr key={c.checkKey}>
                  <th scope="row">
                    <button type="button" onClick={() => props.onOpen(c.checkKey)}>
                      {c.name}
                    </button>
                    <div className="detail">{c.benchmarkControlId ?? c.checkKey}</div>
                  </th>
                  <td>{c.machinesFailed}</td>
                  <td>{c.machinesPassed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </section>
  );
}

function CheckMachineTable(props: { family: MetricFamily; checkKey: string; scope: string }) {
  const api = useMetricsApi();
  const state = useAsync(
    (s) => api.checkMachines(props.family, props.checkKey, props.scope || undefined, s),
    [api, props.family, props.checkKey, props.scope],
  );
  return (
    <section aria-labelledby="cm-h">
      <h3 id="cm-h">Machines for {props.checkKey}</h3>
      {state.status === "loading" && <Loading what="machines" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" &&
        (state.data.machines.length === 0 ? (
          <Empty>No machine has a fresh result for this check.</Empty>
        ) : (
          <table>
            <caption className="sr-only">Machines and their result for this check</caption>
            <thead>
              <tr>
                <th scope="col">Machine</th>
                <th scope="col">Result</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {state.data.machines.map((m: CheckMachineRow) => (
                <tr key={m.machineId}>
                  <th scope="row">
                    {m.name}
                    <div className="detail">{shortId(m.subscriptionId)}</div>
                  </th>
                  <td>
                    <ToneBadge
                      tone={m.status === "Compliant" ? "good" : "bad"}
                      label={m.status === "Compliant" ? "Passing" : "Failing"}
                    />
                  </td>
                  <td>
                    {m.reasons.length === 0
                      ? "—"
                      : m.reasons.map((r) => (
                          <div key={r.phrase}>
                            {r.phrase}
                            {r.expected != null && ` (expected ${r.expected}, actual ${r.actual ?? "n/a"})`}
                          </div>
                        ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </section>
  );
}

function MachineTable({ family, scope }: { family: MetricFamily; scope: string }) {
  const api = useMetricsApi();
  const state = useAsync((s) => api.machines(family, s), [api, family]);
  return (
    <section aria-labelledby="mach-h">
      <h3 id="mach-h">Machines</h3>
      {state.status === "loading" && <Loading what="machines" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" &&
        (() => {
          const rows = state.data.machines.filter((m) => !scope || m.subscriptionId === scope);
          if (rows.length === 0) return <Empty>No machines in this scope.</Empty>;
          return (
            <table>
              <caption className="sr-only">Machine evidence status</caption>
              <thead>
                <tr>
                  <th scope="col">Machine</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Reported state</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m: MachineRow) => (
                  <tr key={m.machineId}>
                    <th scope="row">
                      {m.name}
                      <div className="detail">
                        {m.kind} · {shortId(m.subscriptionId)}
                      </div>
                    </th>
                    <td>{QUALITY_LABEL[m.evidenceQuality]}</td>
                    <td>
                      <ToneBadge
                        tone={qualityTone(m.evidenceQuality, m.reportedState)}
                        label={
                          m.evidenceQuality !== "Fresh"
                            ? "Not assessed"
                            : (m.reportedState ?? "No data")
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          );
        })()}
    </section>
  );
}
