import { USE_MOCK_DATA } from "../api/context";
import type { MetricFamily } from "../api/types";
import { FAMILY_LABEL } from "../lib/format";

/** Evidence-honesty labels: what the numbers are and are not. */
export function EvidenceNotice({ labels, family }: { labels: string[]; family?: MetricFamily }) {
  return (
    <aside className="notice" aria-label={family ? `Evidence notes: ${FAMILY_LABEL[family]}` : "Evidence notes"}>
      {USE_MOCK_DATA && (
        <p>
          <strong>Synthetic demo data.</strong> Nothing here comes from a live Azure environment.
        </p>
      )}
      {family === "CISWindowsSecurityBaseline" && (
        <p>
          <strong>CIS evidence is not verified as live.</strong> Applicability and control mapping
          are unverified until checked against an authorized actual report; synthetic CIS data is
          never live evidence.
        </p>
      )}
      <ul>
        {labels.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </aside>
  );
}
