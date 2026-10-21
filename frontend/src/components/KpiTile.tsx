import { useId, useState } from "react";
import { Link } from "react-router-dom";
import type { Kpi } from "../api/policyTypes";
import { deltaView, drillSearch, fmtValue, formatWhen } from "../lib/policyFormat";
import { Sparkline } from "./charts";

export function KpiTile({ kpi, snapshotAt }: { kpi: Kpi; snapshotAt: string | null }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const delta = deltaView(kpi);
  const noData = kpi.status === "no-data";
  return (
    <article className={`kpi ${noData ? "kpi-nodata" : ""}`} aria-labelledby={`${id}-t`}>
      <h3 id={`${id}-t`} className="kpi-label">{kpi.label}</h3>
      <p className="kpi-value">{fmtValue(kpi)}</p>
      {kpi.numerator !== null && kpi.denominator !== null && (
        <p className="kpi-frac">{kpi.numerator.toLocaleString("en")} of {kpi.denominator.toLocaleString("en")} · {kpi.grain}</p>
      )}
      {(kpi.numerator === null || kpi.denominator === null) && <p className="kpi-frac">{kpi.grain}</p>}
      <p className={`kpi-delta delta-${delta.tone}`}>{delta.text}</p>
      <Sparkline values={kpi.sparkline} label={`${kpi.label} trend`} />
      {kpi.note && <p className="kpi-note">{kpi.note}</p>}
      <div className="kpi-actions">
        <button type="button" className="link-btn" aria-expanded={open} aria-controls={`${id}-p`} onClick={() => setOpen((o) => !o)}>
          How is this calculated?
        </button>
        {kpi.drill && (
          <Link to={`/explorer${drillSearch(kpi.drill)}`} className="link-btn">
            Show the rows
          </Link>
        )}
      </div>
      {open && (
        <div id={`${id}-p`} className="popover" role="region" aria-label={`How ${kpi.label} is calculated`}>
          <p>{kpi.formula}</p>
          <dl>
            <dt>Grain</dt>
            <dd>{kpi.grain}</dd>
            <dt>Numerator</dt>
            <dd>{kpi.numerator ?? "n/a"}</dd>
            <dt>Denominator</dt>
            <dd>{kpi.denominator ?? "n/a"}</dd>
            <dt>Snapshot</dt>
            <dd>{formatWhen(snapshotAt)}</dd>
            {kpi.previousAt && (
              <>
                <dt>Previous snapshot</dt>
                <dd>{formatWhen(kpi.previousAt)}</dd>
              </>
            )}
          </dl>
        </div>
      )}
    </article>
  );
}
