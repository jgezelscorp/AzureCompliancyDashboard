import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { TONE_TEXT, type Tone } from "../lib/format";

const ICON: Record<Tone, string> = { good: "✔", warn: "▲", bad: "✖", nodata: "∅", stale: "⏱" };

export function ToneBadge({ tone, label }: { tone: Tone; label?: string }) {
  return (
    <span className={`badge tone-${tone}`}>
      <span aria-hidden="true">{ICON[tone]}</span> {label ?? TONE_TEXT[tone]}
    </span>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <div role="status" className="state state-loading">
      <p>Loading {what}…</p>
      <div className="skeleton-row" aria-hidden="true">
        <span className="skeleton" />
        <span className="skeleton" />
        <span className="skeleton" />
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state state-empty">{children}</p>;
}

export function errorMessage(error: Error): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session is not valid. Please sign in again.";
    if (error.status === 403) {
      return "Access denied: you have no authorized onboarded scope, or your Azure access could not be verified. Nothing is shown rather than guessing.";
    }
    return `The service returned an error (${error.status}).`;
  }
  return "The service could not be reached.";
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="state state-error">
      <p>{errorMessage(error)}</p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function MetricCard(props: {
  title: string;
  value: string;
  tone: Tone;
  detail: ReactNode;
}) {
  return (
    <div className={`card tone-border-${props.tone}`} role="group" aria-label={props.title}>
      <h4>{props.title}</h4>
      <p className="metric">{props.value}</p>
      <ToneBadge tone={props.tone} />
      <p className="detail">{props.detail}</p>
    </div>
  );
}
