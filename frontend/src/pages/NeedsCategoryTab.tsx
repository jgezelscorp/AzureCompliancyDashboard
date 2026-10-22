import { useState } from "react";
import { ApiError } from "../api/client";
import { useDomainApi } from "../api/domainContext";
import { CONFIDENCES, type Confidence, type OverrideRow, type QueueRow } from "../api/domainTypes";
import { Empty, ErrorState, Loading, errorText } from "../components/common";
import { DataGrid, type Column } from "../components/DataGrid";
import { DomainCell, ProvenanceBadge } from "../components/ProvenanceBadge";
import { useAsync } from "../hooks/useAsync";
import { CONFIDENCE_META, downloadCsv, familyLabel, queueCsv } from "../lib/domainFormat";
import { formatWhen } from "../lib/policyFormat";
import { fmtInt } from "../lib/format";

export interface QueueView {
  qkind: "all" | "policy" | "check";
  qconf: string[];
  qq: string;
  offset: number;
}

const PAGE = 25;

function assignFailure(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Not permitted: only users with Azure deployments/write on the configuration anchor resource group can edit shared configuration.";
    if (e.status === 409) return "The override limit has been reached; remove an override first.";
    if (e.status === 422) return "The chosen domain is not part of the taxonomy.";
    return `Could not save the override. ${errorText(e.status)}`;
  }
  return "Could not save the override.";
}

/** Editing needs both the caller's Azure-RBAC permission and the deployment gate; the API enforces both again. */
function useEditGate() {
  const api = useDomainApi();
  const caps = useAsync((s) => api.capabilities(s), []);
  const ov = useAsync((s) => api.overrides(s), []);
  const canEdit = caps.status === "ready" && caps.data.canEditSharedConfig && ov.status === "ready" && ov.data.gateEnabled;
  let why: string | null = null;
  if (ov.status === "ready" && !canEdit) {
    why = ov.data.gateEnabled
      ? "Your Azure access does not allow editing shared configuration, so assignment is disabled. Ask someone with write access on the configuration anchor resource group."
      : ov.data.editing;
    if (ov.data.gateEnabled && caps.status === "error") why = "Your editing permission could not be verified, so assignment is disabled.";
  }
  return { caps, ov, canEdit, why };
}

function GateNotice({ why, repoOverrides }: { why: string | null; repoOverrides?: number }) {
  if (!why) return null;
  return (
    <div className="state state-stale" role="status" data-testid="gate-notice">
      <p>{why}</p>
      <p className="detail">
        Fallback: set <code>ACD_DOMAIN_OVERRIDES</code> or <code>ACD_DOMAIN_OVERRIDES_FILE</code> in the deployment configuration.
        {repoOverrides ? ` ${repoOverrides} repo-managed override(s) are active.` : ""}
      </p>
    </div>
  );
}

export function NeedsCategoryTab({ view, update }: { view: QueueView; update: (p: Partial<QueueView>) => void }) {
  const api = useDomainApi();
  const gate = useEditGate();
  const tax = useAsync((s) => api.taxonomy(s), []);
  const queue = useAsync(
    (s) => api.queue({ kind: view.qkind, confidence: view.qconf, q: view.qq, limit: PAGE, offset: view.offset }, {}, s),
    [JSON.stringify(view)],
  );
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const domains = tax.status === "ready" ? tax.data.domains : [];
  const rowId = (r: QueueRow) => `${r.kind}|${r.family ?? ""}|${r.key}`;

  const assign = async (r: QueueRow) => {
    const domain = picked[rowId(r)] ?? r.suggestedDomain ?? "";
    if (!domain) return;
    setBusy(rowId(r));
    setMessage(null);
    try {
      await api.createOverride({ target: r.kind, pattern: r.key, domain });
      setMessage({ ok: true, text: `Assigned “${r.name}” to ${domains.find((d) => d.id === domain)?.label ?? domain}. Domains were recomputed; the queue is refreshed.` });
      queue.reload();
      gate.ov.reload();
    } catch (e) {
      setMessage({ ok: false, text: assignFailure(e) });
    } finally {
      setBusy(null);
    }
  };

  const cols: Column<QueueRow>[] = [
    { id: "kind", header: "Kind", render: (r) => (r.kind === "policy" ? "Policy" : "Check") },
    {
      id: "name",
      header: "Name",
      rowHeader: true,
      render: (r) => (
        <>
          {r.name}
          <div className="detail">{r.family ? `${familyLabel(r.family)} · ` : ""}{r.category ?? "no category"}</div>
        </>
      ),
    },
    { id: "cur", header: "Current domain", render: (r) => <DomainCell domain={r.domain} label={r.domainLabel} confidence={r.domainConfidence} source={r.domainSource} /> },
    { id: "ev", header: "Evaluations", numeric: true, render: (r) => `${fmtInt(r.nonCompliant)} of ${fmtInt(r.evaluations)} failing` },
    { id: "sug", header: "Suggested", render: (r) => (r.suggestedDomain ? domains.find((d) => d.id === r.suggestedDomain)?.label ?? r.suggestedDomain : "no suggestion") },
    {
      id: "assign",
      header: "Assign domain",
      render: (r) => {
        const value = picked[rowId(r)] ?? r.suggestedDomain ?? "";
        return (
          <span className="assign">
            <select
              aria-label={`Domain for ${r.name}`}
              value={value}
              disabled={!gate.canEdit || busy !== null}
              onChange={(e) => setPicked((p) => ({ ...p, [rowId(r)]: e.target.value }))}
            >
              <option value="">Choose…</option>
              {domains.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>{" "}
            <button type="button" className="btn" aria-label={`Assign ${r.name}`} disabled={!gate.canEdit || !value || busy !== null} onClick={() => void assign(r)}>
              Assign
            </button>
          </span>
        );
      },
    },
  ];

  const toggleConf = (c: Confidence) =>
    update({ qconf: view.qconf.includes(c) ? view.qconf.filter((x) => x !== c) : [...view.qconf, c] });

  return (
    <>
      <p className="grain">
        Items whose domain is unmapped or only keyword-derived. An assignment is saved as an override: it takes precedence over rules, is shown as “Override”, and changes how the item is counted from the next recompute (done on save).
      </p>
      {gate.ov.status === "loading" && <Loading what="editing permissions" />}
      <GateNotice why={gate.why} repoOverrides={gate.ov.status === "ready" ? gate.ov.data.repoOverrides : undefined} />
      <form className="filter-bar no-print" role="search" aria-label="Queue filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Kind
          <select value={view.qkind} onChange={(e) => update({ qkind: e.target.value as QueueView["qkind"] })}>
            <option value="all">Policies and checks</option>
            <option value="policy">Policies</option>
            <option value="check">Checks</option>
          </select>
        </label>
        <fieldset className="conf-filter">
          <legend>Provenance</legend>
          {CONFIDENCES.map((c) => (
            <label key={c}>
              <input type="checkbox" checked={view.qconf.includes(c)} onChange={() => toggleConf(c)} /> {CONFIDENCE_META[c].label}
            </label>
          ))}
          <span className="detail">{view.qconf.length === 0 ? "Default: Unmapped and Derived (low)." : ""}</span>
        </fieldset>
        <label>
          Search
          <input type="search" value={view.qq} placeholder="name or key" onChange={(e) => update({ qq: e.target.value })} />
        </label>
      </form>
      {message && (
        <p role={message.ok ? "status" : "alert"} className={`state ${message.ok ? "state-empty" : "state-error"}`}>
          {message.text}
        </p>
      )}
      {queue.status === "loading" && <Loading what="the Needs-category queue" />}
      {queue.status === "error" && <ErrorState error={queue.error} onRetry={queue.reload} />}
      {queue.status === "ready" &&
        (queue.data.total === 0 ? (
          <Empty>Nothing needs a category for these filters. Every item in scope has a domain with the selected provenance.</Empty>
        ) : (
          <>
            <p className="grain">
              {fmtInt(queue.data.summary?.policy)} policies and {fmtInt(queue.data.summary?.check)} checks match. Taxonomy v{queue.data.taxonomyVersion}.
            </p>
            <p className="no-print">
              <button type="button" className="btn" onClick={() => downloadCsv("needs-category.csv", queueCsv(queue.data.rows, queue.data.total))}>Export this page as CSV</button>
            </p>
            <DataGrid
              caption="Needs-category queue"
              columns={cols}
              rows={queue.data.rows}
              rowKey={rowId}
              total={queue.data.total}
              offset={queue.data.offset}
              limit={PAGE}
              onPage={(offset) => update({ offset })}
            />
          </>
        ))}
    </>
  );
}

export function OverridesTab() {
  const api = useDomainApi();
  const gate = useEditGate();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const remove = async (o: OverrideRow) => {
    setMessage(null);
    try {
      await api.deleteOverride(o.id);
      setMessage({ ok: true, text: `Removed the override for “${o.pattern}”. Domains were recomputed.` });
      gate.ov.reload();
    } catch (e) {
      setMessage({ ok: false, text: assignFailure(e) });
    }
  };
  if (gate.ov.status === "loading") return <Loading what="overrides" />;
  if (gate.ov.status === "error") return <ErrorState error={gate.ov.error} onRetry={gate.ov.reload} />;
  const { overrides, repoOverrides } = gate.ov.data;
  return (
    <>
      <p className="grain">Overrides decided by reviewers; each one is exact-match on a policy definition or a check key. {repoOverrides} additional override(s) come from repo or environment configuration and are not listed or editable here.</p>
      <GateNotice why={gate.why} repoOverrides={repoOverrides} />
      {message && (
        <p role={message.ok ? "status" : "alert"} className={`state ${message.ok ? "state-empty" : "state-error"}`}>
          {message.text}
        </p>
      )}
      {overrides.length === 0 ? (
        <Empty>No overrides have been saved in the app yet.</Empty>
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Overrides (scrollable)">
          <table className="data-table">
            <caption className="sr-only">Domain overrides</caption>
            <thead>
              <tr>
                <th scope="col">Applies to</th>
                <th scope="col">Match</th>
                <th scope="col">Domain</th>
                <th scope="col">Note</th>
                <th scope="col">Saved</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {overrides.map((o) => (
                <tr key={o.id}>
                  <th scope="row">{o.target === "policy" ? "Policy" : "Check"}</th>
                  <td>{o.pattern}</td>
                  <td><ProvenanceBadge confidence="override" /> {o.domain}</td>
                  <td>{o.note ?? ""}</td>
                  <td>{formatWhen(o.createdAt)}</td>
                  <td>
                    <button type="button" className="btn" aria-label={`Delete override for ${o.pattern}`} disabled={!gate.canEdit} onClick={() => void remove(o)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
