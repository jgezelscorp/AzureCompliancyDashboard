# Metrics specification (I02)

Normative contract for all reporting surfaces (app, workbook, exports). Python and KQL implementations must produce identical values on the golden fixtures in `tests\fixtures\`. The Python reference is `scripts\metrics_reference.py`; schemas are in `contracts\schemas\`.

## Principles

1. **Three separate metrics.** Azure Policy compliance %, check pass rate and coverage are never blended into one number or one "score". Each is always shown with its label, numerator and denominator.
2. **Missing or stale data is never green.** A machine/family is green only when evidence quality is `Fresh` **and** the reported state is `Compliant`.
3. **No certification claims.** Results describe Azure Policy / Machine Configuration reports. They never state or imply CIS, ISO, NIS2, DORA or any other certification or attestation.
4. **Distinct baseline families.** `AzureWindowsBaseline` and `CISWindowsSecurityBaseline` are separate families. Every metric is computed per family; baseline evidence never counts as CIS evidence, and cross-family comparison does not imply equivalence. Native CIS applicability stays "unverified" until gate G-APP passes.
5. **Reasons are not checks.** A check may have several reasons; only unique `checkKey` values are counted.
6. **No fabricated precision.** A ratio with a zero denominator is `null` (rendered "no data"), never 0% or 100%.

## Evidence quality (separate from reported state)

Reported state (`Compliant`, `NonCompliant`, `Pending`, `Unknown`) is independent of evidence quality: `Fresh`, `Stale`, `UnknownAge`, `MissingAssignment`, `NoReport`, `UnknownApplicability`, `Unsupported`, `AccessDenied`, `ProviderUnavailable`, `Partial`, `CollectionFailure`, `OutOfScope`.

Freshness uses the latest report per machine and family: `snapshotAt - report.endTime <= 24h` is `Fresh`; greater is `Stale`; missing timestamp is `UnknownAge`. The 24h threshold is a contract constant. Eligibility `Unknown` yields `UnknownApplicability`; no assignment yields `MissingAssignment`; assignment without report yields `NoReport`.

## Metric 1: Azure Policy compliance %

Source: policy states (`policy-state.schema.json`), per baseline family.

`percent = Compliant / (Compliant + NonCompliant) * 100`

- Resource-level (machine x assignment) grain.
- `Exempt`, `Conflict`, `NotStarted`, `Unknown` are excluded from the denominator and reported as separate counts (`exempt`, `other`); expiring exemptions remain visible.
- Policy compliance says nothing about individual checks or about machines with no state.

## Metric 2: Check pass rate

Source: normalized checks (`check.schema.json`) in the latest **Fresh** report per eligible machine and family.

`percent = unique checks Compliant / unique checks total * 100`

- Counts are over unique `checkKey` per report; reasons are ignored for counting.
- Stale, unknown-age and missing reports are **excluded** from the headline and surfaced as `reportsExcludedAsNotFresh`; they are never treated as passing.
- Golden: synthetic Arc `AzureWindowsBaseline` report = 373 unique checks, 109 Compliant, 264 NonCompliant (pass rate 29.22%), with 479 reasons that are not counted as checks.

## Metric 3: Coverage

Per family over machines with eligibility `Eligible`; `Unknown` eligibility is reported separately (`unknownEligibility`) and is never counted as covered or as excluded.

| Field | Definition |
|---|---|
| `eligible` | Machines with eligibility `Eligible` |
| `assigned` | Eligible machines with an assignment for the family |
| `usableReport` | Eligible machines with a report (`Fresh`, `Stale` or `UnknownAge`) |
| `freshReport` | Eligible machines whose latest report is `Fresh` |
| `*Percent` | Count / `eligible` * 100, `null` when `eligible` is 0 |

Inventory counts (for example Azure VMs vs Arc machines) are not Windows eligibility and not assessment coverage.

## Machine status

`green = (evidenceQuality == Fresh) AND (reportedState == Compliant)`. Everything else is not green: NonCompliant, Pending, Unknown, and every non-Fresh quality value. UIs must show the evidence-quality reason, not just a colour.

## Fixtures and validation

| Fixture | Purpose |
|---|---|
| `arc-azurewindowsbaseline-373.json` | Observed Arc AzureWindowsBaseline report shape, fully synthetic |
| `cis-synthetic-mixed.json` | **Synthetic** native CIS cases (fresh pass/fail, stale, missing assignment, unknown eligibility, no report, exempt). Not verified CIS evidence (gate G-SHAPE/G-DIST) |
| `empty-estate.json` | Null ratios on empty input |
| `dual-family-distinct.json` | Baseline evidence never satisfies CIS |

Every fixture carries `"synthetic": true`, uses placeholder IDs (`00000000-0000-0000-0000-000000000000`) and fictional names. Regenerate with `python scripts\generate_fixtures.py`; validate with `python scripts\validate_fixtures.py` (needs `pip install jsonschema`). Generation is deterministic.
