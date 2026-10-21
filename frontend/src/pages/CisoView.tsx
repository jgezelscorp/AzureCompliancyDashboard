import { useMetricsApi } from "../api/context";
import type { EvidenceQuality, FamilyMetrics, LatestMetrics, MetricFamily } from "../api/types";
import { Empty, ErrorState, Loading, ToneBadge } from "../components/common";
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
  toneFor,
  type Tone,
} from "../lib/format";

/** Headline status for one baseline. Partial coverage caps it: it can never read healthy. */
export function postureFor(m: FamilyMetrics, stale: boolean): { tone: Tone; text: string } {
  const pass = m.checkPassRate.percent;
  const fresh = m.coverage.freshReportPercent;
  if (m.coverage.eligible === 0 || pass === null) {
    return { tone: "nodata", text: "No fresh evidence: posture cannot be assessed." };
  }
  if (stale) return { tone: "stale", text: "Evidence is stale: posture is not current." };
  if (fresh !== null && fresh < 100) {
    const tone = toneFor(pass, false);
    return {
      tone: tone === "good" ? "warn" : tone,
      text: `Partial picture: only ${formatPercent(fresh)} of eligible machines have fresh evidence.`,
    };
  }
  return { tone: toneFor(pass, false), text: `${formatPercent(pass)} of checks pass on fresh evidence.` };
}

export function CisoView() {
  const api = useMetricsApi();
  const state = useAsync((s) => api.latest(s), [api]);
  if (state.status === "loading") return <Loading what="posture" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  const latest = state.data;
  if (latest.snapshotAt === null) {
    return (
      <section aria-labelledby="ciso-h">
        <h2 id="ciso-h">CISO view</h2>
        <Empty>
          No evidence has been collected for your authorized scopes yet. No data is not compliance.
        </Empty>
        <EvidenceNotice labels={latest.labels} />
      </section>
    );
  }
  return (
    <section aria-labelledby="ciso-h">
      <h2 id="ciso-h">CISO view</h2>
      <p className="detail">
        Snapshot {formatTimestamp(latest.snapshotAt)} · {latest.scope.authorizedSubscriptions} of{" "}
        {latest.scope.onboardedSubscriptions} onboarded subscription(s) visible to you
      </p>
      {latest.dataStale && (
        <p role="alert" className="state state-stale">
          The latest collection is older than {latest.freshnessHours ?? 24} hours; nothing below is
          presented as healthy.
        </p>
      )}
      <EvidenceNotice labels={latest.labels} />
      {FAMILIES.map((family) => (
        <FamilyPosture key={family} family={family} latest={latest} />
      ))}
      <CoverageGaps />
    </section>
  );
}

function FamilyPosture({ family, latest }: { family: MetricFamily; latest: LatestMetrics }) {
  const m = latest.families.find((f) => f.family === family);
  return (
    <section aria-labelledby={`posture-${family}`} className="family">
      <h3 id={`posture-${family}`}>{FAMILY_LABEL[family]}</h3>
      {!m ? (
        <Empty>No metrics for this baseline.</Empty>
      ) : (
        <>
          <p className="headline">
            <ToneBadge tone={postureFor(m, latest.dataStale).tone} />{" "}
            {postureFor(m, latest.dataStale).text}
          </p>
          {family === "CISWindowsSecurityBaseline" && (
            <EvidenceNotice labels={[]} family={family} />
          )}
          <FamilyMetricCards metrics={m} stale={latest.dataStale} />
          <TrendBlock family={family} />
          <TopRisks family={family} />
        </>
      )}
    </section>
  );
}

function TrendBlock({ family }: { family: MetricFamily }) {
  const api = useMetricsApi();
  const state = useAsync((s) => api.history(family, s), [api, family]);
  if (state.status === "loading") return <Loading what="trend" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  return (
    <Trend
      series={seriesFrom(state.data.points, state.data.aggregatesIncluded)}
      samplingNote={state.data.samplingNote}
    />
  );
}

function TopRisks({ family }: { family: MetricFamily }) {
  const api = useMetricsApi();
  const state = useAsync((s) => api.categories(family, undefined, s), [api, family]);
  return (
    <div>
      <h4>Top risks</h4>
      {state.status === "loading" && <Loading what="risks" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" &&
        (() => {
          const risks = state.data.categories
            .filter((c) => c.total > c.passed)
            .sort((a, b) => (a.percent ?? 100) - (b.percent ?? 100))
            .slice(0, 5);
          if (risks.length === 0) {
            return <Empty>No failing checks on fresh evidence. Coverage gaps below still apply.</Empty>;
          }
          return (
            <ol>
              {risks.map((c) => (
                <li key={c.category}>
                  {c.category}: {formatPercent(c.percent)} pass, {c.total - c.passed} failing check
                  result(s)
                </li>
              ))}
            </ol>
          );
        })()}
    </div>
  );
}

const GAP_ORDER: EvidenceQuality[] = [
  "MissingAssignment",
  "NoReport",
  "Stale",
  "UnknownAge",
  "UnknownApplicability",
];

function CoverageGaps() {
  const api = useMetricsApi();
  const state = useAsync(
    async (s) => Promise.all(FAMILIES.map((f) => api.machines(f, s))),
    [api],
  );
  return (
    <section aria-labelledby="gaps-h">
      <h3 id="gaps-h">Coverage gaps</h3>
      {state.status === "loading" && <Loading what="coverage gaps" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ready" &&
        (() => {
          const rows = state.data.flatMap((resp) =>
            GAP_ORDER.map((q) => ({
              family: resp.family,
              quality: q,
              names: resp.machines.filter((m) => m.evidenceQuality === q).map((m) => m.name),
            })).filter((r) => r.names.length > 0),
          );
          if (rows.length === 0) return <Empty>Every visible machine has fresh evidence.</Empty>;
          return (
            <table>
              <caption className="sr-only">Machines without fresh evidence by baseline</caption>
              <thead>
                <tr>
                  <th scope="col">Baseline</th>
                  <th scope="col">Gap</th>
                  <th scope="col">Machines</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.family}-${r.quality}`}>
                    <th scope="row">{FAMILY_LABEL[r.family]}</th>
                    <td>
                      <ToneBadge
                        tone={r.quality === "Stale" || r.quality === "UnknownAge" ? "stale" : "nodata"}
                        label={QUALITY_LABEL[r.quality]}
                      />
                    </td>
                    <td>
                      {r.names.length}: {r.names.join(", ")}
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
