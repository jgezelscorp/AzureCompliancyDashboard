import type { HistoryPoint } from "../api/types";
import { formatTimestamp } from "../lib/format";

export interface TrendSeries {
  label: string;
  values: { at: string; value: number | null }[];
}

/** Pulls a percentage series out of history: aggregate pass rate when allowed, else green machines. */
export function seriesFrom(points: HistoryPoint[], aggregates: boolean): TrendSeries {
  if (aggregates && points.some((p) => p.checkPassRate)) {
    return {
      label: "Check pass rate (%)",
      values: points.map((p) => ({ at: p.snapshotAt, value: p.checkPassRate?.percent ?? null })),
    };
  }
  return {
    label: "Machines green on fresh evidence (%)",
    values: points.map((p) => ({
      at: p.snapshotAt,
      value:
        p.machineSummary.machines === 0
          ? null
          : Math.round((1000 * p.machineSummary.green) / p.machineSummary.machines) / 10,
    })),
  };
}

const W = 320;
const H = 90;
const PAD = 6;

export function Trend({ series, samplingNote }: { series: TrendSeries; samplingNote?: string }) {
  const known = series.values.filter((v) => v.value !== null);
  if (series.values.length === 0) return <p className="state state-empty">No history yet.</p>;
  const x = (i: number) =>
    series.values.length > 1 ? PAD + (i * (W - 2 * PAD)) / (series.values.length - 1) : W / 2;
  const y = (v: number) => PAD + (1 - v / 100) * (H - 2 * PAD);
  let path = "";
  series.values.forEach((v, i) => {
    if (v.value === null) return;
    const cmd = path === "" || series.values[i - 1]?.value === null ? "M" : "L";
    path += `${cmd}${x(i).toFixed(1)},${y(v.value).toFixed(1)} `;
  });
  const last = known.at(-1);
  return (
    <figure className="trend">
      <figcaption>
        {series.label}
        {last ? ` — latest ${last.value?.toFixed(1)}%` : " — no data points"}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${series.label} trend, ${known.length} samples`}>
        <line x1="0" y1={H - PAD} x2={W} y2={H - PAD} stroke="currentColor" strokeOpacity="0.4" />
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
        {series.values.map((v, i) =>
          v.value === null ? null : (
            <circle key={v.at} className="trend-point" cx={x(i)} cy={y(v.value)} r="3.5" fill="currentColor" />
          ),
        )}
      </svg>
      {known.length < 3 && (
        <p className="detail">
          Only {known.length} {known.length === 1 ? "sample" : "samples"} so far; a trend line appears as more
          collections complete (every few hours).
        </p>
      )}
      {samplingNote && <p className="detail">{samplingNote} Gaps mean no sample, not compliance.</p>}
      <details>
        <summary>Show values as a table</summary>
        <table>
          <caption className="sr-only">{series.label} by collection time</caption>
          <thead>
            <tr>
              <th scope="col">Collected</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {series.values.map((v) => (
              <tr key={v.at}>
                <td>{formatTimestamp(v.at)}</td>
                <td>{v.value === null ? "No data" : `${v.value.toFixed(1)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
