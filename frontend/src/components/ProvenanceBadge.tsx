import { CONFIDENCE_META, isConfidence } from "../lib/domainFormat";

export function ProvenanceBadge({ confidence, source }: { confidence: string | null | undefined; source?: string | null }) {
  const meta = isConfidence(confidence) ? CONFIDENCE_META[confidence] : null;
  const label = meta?.label ?? "Not classified";
  const tone = meta?.tone ?? "nodata";
  return (
    <span className={`badge tone-${tone}`} title={`${meta?.hint ?? "No provenance reported."}${source ? ` (source: ${source})` : ""}`}>
      <span aria-hidden="true">{meta?.icon ?? "∅"}</span> <span className="sr-only">Provenance: </span>
      {label}
    </span>
  );
}

export function DomainBadge({ label, domain }: { label?: string; domain: string | null | undefined }) {
  return <span className="domain-chip">{label ?? domain ?? "other"}</span>;
}

/** Domain with its provenance, the single way a classification is displayed in tables. */
export function DomainCell({ domain, label, confidence, source }: { domain?: string | null; label?: string; confidence?: string | null; source?: string | null }) {
  return (
    <span className="domain-cell">
      <DomainBadge domain={domain} label={label} /> <ProvenanceBadge confidence={confidence} source={source} />
    </span>
  );
}
