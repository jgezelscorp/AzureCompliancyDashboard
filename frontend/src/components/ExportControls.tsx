import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { useMetricsApi } from "../api/context";
import type { ExportJob, ExportRequest } from "../api/types";
import { formatTimestamp } from "../lib/format";

export interface ExportOption {
  label: string;
  request: ExportRequest;
}

function failureText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Export denied: your Azure access could not be re-verified or has changed.";
    if (e.status === 410) return "This export has expired. Create a new one.";
    if (e.status === 409) return "There is no collected evidence to export yet.";
    if (e.status === 413) return "The export is too large. Narrow the scope and try again.";
    if (e.status === 429) return "Too many active exports. Wait for existing ones to expire.";
    return `The export failed (${e.status}).`;
  }
  return "The service could not be reached.";
}

/** Export buttons plus job status. Files are short-lived, re-authorized on download, never linkable. */
export function ExportControls({ options }: { options: ExportOption[] }) {
  const api = useMetricsApi();
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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

  return (
    <section aria-labelledby="export-h" className="exports">
      <h3 id="export-h">Export</h3>
      <p className="detail">
        Exports use the same authorized scope and snapshot as this page, are re-checked against your
        Azure access when created and again when downloaded, and expire after 15 minutes. They
        state their scope, snapshot, freshness and evidence limits and are not a certification.
      </p>
      <div role="group" aria-label="Create export">
        {options.map((o) => (
          <button key={o.label} type="button" disabled={busy} onClick={() => void create(o.request)}>
            {o.label}
          </button>
        ))}
      </div>
      {message && (
        <p role="alert" className="state state-error">
          {message}
        </p>
      )}
      {jobs.length > 0 && (
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
            {jobs.map((j) => (
              <tr key={j.jobId}>
                <th scope="row">
                  {j.kind}
                  <div className="detail">
                    {j.family} · snapshot {j.snapshotAt ? formatTimestamp(j.snapshotAt) : "n/a"}
                    {j.truncated && " · truncated"}
                  </div>
                </th>
                <td>{j.status === "completed" ? "Ready" : j.status === "expired" ? "Expired" : "Failed"}</td>
                <td>{formatTimestamp(j.expiresAt)}</td>
                <td>
                  {j.status === "completed" ? (
                    <button type="button" onClick={() => void download(j)}>
                      Download
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
