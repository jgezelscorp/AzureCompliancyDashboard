import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { useMetricsApi } from "../api/context";
import { errorText } from "./common";
import type { ExportJob, ExportRequest } from "../api/types";
import { formatTimestamp } from "../lib/format";

export interface ExportOption {
  label: string;
  request: ExportRequest;
}

function failureText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403)
      return "Export denied: your Azure access could not be re-verified or has changed.";
    if (e.status === 410) return "This export has expired. Create a new one.";
    if (e.status === 409)
      return "There is no collected evidence to export yet.";
    if (e.status === 413)
      return "The export is too large. Narrow the scope and try again.";
    if (e.status === 429)
      return "Too many active exports. Wait for existing ones to expire.";
    if (e.status <= 0) return `Export failed: ${errorText(e.status)}`;
    return `The export failed (${e.status}).`;
  }
  return "The service could not be reached.";
}

const KEY_COLLAPSED = "acd.export.collapsed";
const KEY_HIDDEN = "acd.export.hidden";
const KEY_DISMISSED = "acd.export.dismissed";

function readStore(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStore(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private mode); the preference then lasts for this view only.
  }
}

function usePersistedFlag(key: string): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState(() => readStore(key) === "1");
  const set = useCallback(
    (v: boolean) => {
      setValue(v);
      writeStore(key, v ? "1" : null);
    },
    [key],
  );
  return [value, set];
}

function readDismissed(): string[] {
  try {
    const parsed: unknown = JSON.parse(readStore(KEY_DISMISSED) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string")
      : [];
  } catch {
    return [];
  }
}

/** Export buttons plus job status. Files are short-lived, re-authorized on download, never linkable. */
export function ExportControls({ options }: { options: ExportOption[] }) {
  const api = useMetricsApi();
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [collapsed, setCollapsed] = usePersistedFlag(KEY_COLLAPSED);
  const [hidden, setHidden] = usePersistedFlag(KEY_HIDDEN);
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);

  // The API has no delete endpoint: removal only hides the row in this browser.
  const dismiss = (ids: string[]) => {
    const next = [...new Set([...dismissed, ...ids])].slice(-200);
    setDismissed(next);
    writeStore(KEY_DISMISSED, JSON.stringify(next));
  };

  const refresh = useCallback(async () => {
    try {
      setJobs((await api.listExports()).jobs);
    } catch {
      setJobs([]);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async (request: ExportRequest) => {
    setBusy(true);
    setMessage(null);
    try {
      await api.createExport(request);
      await refresh();
    } catch (e) {
      setMessage(failureText(e));
    } finally {
      setBusy(false);
    }
  };

  const download = async (job: ExportJob) => {
    setMessage(null);
    try {
      const { blob, filename } = await api.downloadExport(job.jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setMessage(failureText(e));
      await refresh();
    }
  };

  if (hidden) {
    return (
      <p className="exports exports-hidden">
        <button type="button" onClick={() => setHidden(false)}>
          Show export section
        </button>
      </p>
    );
  }

  const visible = jobs.filter((j) => !dismissed.includes(j.jobId));
  const finished = visible.filter((j) => j.status !== "completed");

  return (
    <section aria-labelledby="export-h" className="exports">
      <div className="exports-head">
        <h3 id="export-h">Export</h3>
        <button
          type="button"
          aria-expanded={!collapsed}
          aria-controls="export-body"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? "Expand export section" : "Collapse export section"}
        </button>
        <button type="button" onClick={() => setHidden(true)}>
          Hide export section
        </button>
      </div>
      <div id="export-body" hidden={collapsed}>
        <p className="detail">
          Exports use the same authorized scope and snapshot as this page, are
          re-checked against your Azure access when created and again when
          downloaded, and expire after 15 minutes. They state their scope,
          snapshot, freshness and evidence limits and are not a certification.
        </p>
        <div role="group" aria-label="Create export">
          {options.map((o) => (
            <button
              key={o.label}
              type="button"
              disabled={busy}
              onClick={() => void create(o.request)}
            >
              {o.label}
            </button>
          ))}
        </div>
        {message && (
          <p role="alert" className="state state-error">
            {message}
          </p>
        )}
        {visible.length > 0 && (
          <>
            {finished.length > 0 && (
              <p>
                <button
                  type="button"
                  onClick={() => dismiss(finished.map((j) => j.jobId))}
                >
                  Clear finished and expired
                </button>
              </p>
            )}
            <table>
              <caption className="sr-only">Your recent exports</caption>
              <thead>
                <tr>
                  <th scope="col">Export</th>
                  <th scope="col">Status</th>
                  <th scope="col">Expires</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((j) => (
                  <tr key={j.jobId}>
                    <th scope="row">
                      {j.kind}
                      <div className="detail">
                        {j.family} · snapshot{" "}
                        {j.snapshotAt ? formatTimestamp(j.snapshotAt) : "n/a"}
                        {j.truncated && " · truncated"}
                      </div>
                    </th>
                    <td>
                      {j.status === "completed"
                        ? "Ready"
                        : j.status === "expired"
                          ? "Expired"
                          : "Failed"}
                    </td>
                    <td>{formatTimestamp(j.expiresAt)}</td>
                    <td>
                      {j.status === "completed" && (
                        <button type="button" onClick={() => void download(j)}>
                          Download
                        </button>
                      )}{" "}
                      <button
                        type="button"
                        aria-label={`Remove ${j.kind} from list`}
                        onClick={() => dismiss([j.jobId])}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </section>
  );
}
