import type { ReactNode } from "react";
import type { BreakdownRow, TrendPoint } from "../api/policyTypes";

export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) {
    return <span className="spark-empty">{values.length} sample so far</span>;
  }
  const w = 96;
  const h = 28;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 3 - ((v - lo) / span) * (h - 6)).toFixed(1)}`);
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${label}: ${values.length} samples, from ${values[0]} to ${values[values.length - 1]}`}>
      <polyline points={pts.join(" ")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

/** Stacked bar with visible numbers; hatch pattern keeps non-compliant legible without colour. */
export function StackedBar({ row }: { row: BreakdownRow }) {
  const total = row.compliant + row.nonCompliant + row.exempt + row.other;
  if (total === 0) return <span className="bar bar-empty">nothing evaluated</span>;
  const seg = (n: number, cls: string, name: string) =>
    n > 0 ? <span key={name} className={`seg ${cls}`} style={{ width: `${(n / total) * 100}%` }} title={`${name}: ${n}`} /> : null;
  return (
    <span className="bar" role="img" aria-label={`${row.compliant} compliant, ${row.nonCompliant} non-compliant, ${row.exempt} exempt, ${row.other} not assessed of ${total}`}>
      {seg(row.compliant, "seg-good", "Compliant")}
      {seg(row.nonCompliant, "seg-bad", "Non-compliant")}
      {seg(row.exempt, "seg-exempt", "Exempt")}
      {seg(row.other, "seg-other", "Not assessed")}
    </span>
  );
}

export function BarLegend() {
  return (
    <p className="legend" aria-hidden="true">
      <span className="seg seg-good" /> Compliant <span className="seg seg-bad" /> Non-compliant{" "}
      <span className="seg seg-exempt" /> Exempt <span className="seg seg-other" /> Not assessed
    </p>
  );
}

/** Ranked horizontal bars of a count with the underlying numbers printed. */
export function RankedBars({
  items,
  caption,
}: {
  items: { key: string; label: ReactNode; value: number; detail?: ReactNode }[];
  caption: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ol className="ranked" aria-label={caption}>
      {items.map((i) => (
        <li key={i.key}>
          <span className="ranked-label">{i.label}</span>
          <span className="ranked-track" aria-hidden="true">
            <span className="ranked-fill" style={{ width: `${(i.value / max) * 100}%` }} />
          </span>
          <span className="ranked-value">
            {i.value.toLocaleString("en")}
            {i.detail && <span className="muted"> {i.detail}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Oldest to newest; the API returns newest first. Gaps are drawn as dashed connectors and listed. */
export function TrendChart({ points }: { points: TrendPoint[] }) {
  const pts = [...points].reverse().filter((p) => p.percent !== null);
  if (pts.length < 2) {
    return <p className="state state-empty">{pts.length} sample so far: a trend line needs at least two snapshots.</p>;
  }
  const w = 560;
  const h = 150;
  const pad = 28;
  const t0 = new Date(pts[0].at).getTime();
  const t1 = new Date(pts[pts.length - 1].at).getTime();
  const x = (p: TrendPoint) => pad + ((new Date(p.at).getTime() - t0) / Math.max(1, t1 - t0)) * (w - pad * 2);
  const vals = pts.map((p) => p.percent as number);
  const lo = Math.max(0, Math.floor(Math.min(...vals) / 5) * 5 - 5);
  const hi = Math.min(100, Math.ceil(Math.max(...vals) / 5) * 5 + 5);
  const y = (v: number) => h - pad - ((v - lo) / Math.max(1, hi - lo)) * (h - pad * 2);
  return (
    <svg className="trend" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Azure Policy compliance over ${pts.length} samples, ${vals[0].toFixed(1)} % to ${vals[vals.length - 1].toFixed(1)} %`}>
      <text x="2" y={y(hi) + 4} className="axis">{hi}%</text>
      <text x="2" y={y(lo) + 4} className="axis">{lo}%</text>
      {pts.slice(1).map((p, i) => (
        <line key={p.runId} x1={x(pts[i])} y1={y(pts[i].percent as number)} x2={x(p)} y2={y(p.percent as number)} stroke="currentColor" strokeWidth="2" strokeDasharray={p.gapBefore ? "4 4" : undefined} />
      ))}
      {pts.map((p) => (
        <g key={`m${p.runId}`}>
          <circle cx={x(p)} cy={y(p.percent as number)} r="3.5" fill="currentColor" />
          {p.gapBefore && <text x={x(p)} y={h - 6} className="axis" textAnchor="middle">gap</text>}
        </g>
      ))}
    </svg>
  );
}
