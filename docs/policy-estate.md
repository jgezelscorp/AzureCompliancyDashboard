# Estate-wide Azure Policy (data layer, metrics, API)

The standalone app reports on **all** Azure Policy states of the selected subscriptions, not only the
Windows/Machine Configuration families. This page is the single reference for what is collected,
what each number means and which permissions are needed.

## Collected data (read-only, allowlisted)

| Data | Source (see `contracts/source-manifest.json`) | Table |
|------|-----------------------------------------------|-------|
| Latest policy states, every resource type | `policyinsights-querystates` (`$top=1000`, paged) | `policy_states` (+ resource type, group, location, assignment, definition, initiative, effect, group names) |
| Assignments (display name, scope, enforcement mode, sanitized parameters) | `policy-assignments-list` | `policy_assignments` |
| Exemptions (category, expiry) | `policy-exemptions-list` | `policy_exemptions` |
| Definition / initiative metadata (category, severity, effect) | `policy-definitions-get`, `policy-setdefinitions-get` | `policy_definitions`, `policy_initiatives` |
| Inventory + whitelisted tags | `arg-query` (Resources) | `estate_resources` |
| Defender secure score / regulatory standards (optional) | `defender-secure-scores`, `defender-regulatory-standards` | `defender_snapshots` |
| Per-run aggregates for trends | computed | `estate_snapshots` |

Rules:

* Policy category comes from the definition's own metadata. The literal `tbd` returned by Policy Insights is ignored; unresolved definitions show as `Uncategorized`.
* Only tag keys in `ACD_ESTATE_TAG_KEYS` (default `owner,environment,criticality,costcenter,businessunit`) are stored, because tag values can contain personal data.
* Assignment parameters whose names look secret-like (`password`, `key`, `secret`, `token`, ...) are redacted.
* Defender being unavailable (no plan, 403, 404, empty) is recorded as "not available" and is **not** a collection error. It is never shown as a good score.
* Definition metadata is cached: refreshed after 7 days when resolved, retried after 12 hours when unresolved, at most 600 lookups per run.

## Metric definitions

| Metric | Formula | Grain |
|--------|---------|-------|
| Policy compliance % | Compliant / (Compliant + NonCompliant) | policy evaluation (one state record) |
| Resource compliance % | resources with no NonCompliant evaluation / resources with at least one Compliant or NonCompliant evaluation | resource |
| Exempt, Unknown, Conflict, NotStarted | shown apart, never part of the percentage | evaluation |
| High-impact failing policies | distinct failing definitions whose own metadata severity is High/Critical; "n/a" when no definition carries severity | policy |
| Enforcement-class failing policies | distinct failing definitions with effect deny, deployIfNotExists, modify or append | policy |
| Evidence freshness | evaluations newer than `ACD_FRESHNESS_HOURS` (default 24) / all evaluations | evaluation |

There is **no composite risk score**. A group with nothing counted shows "no data", never 100 %.
Trends are the sum of `estate_snapshots` over the viewer's authorized subscriptions; the collection
interval is 6 h, so a young history is labelled "N samples so far" and gaps larger than twice the
interval are flagged.

## Permissions

The collector identity needs only **Reader** at subscription scope (`*/read` covers policy states,
assignments, exemptions, definitions, Resource Graph and Defender reads). **No new role is needed**;
no write permission is added. Policy Insights state reads require
`Microsoft.PolicyInsights/policyStates/queryResults/action`, which Reader includes.

## Cost

PostgreSQL growth is small and bounded: `policy_states` holds only the latest state per
resource/assignment/reference (upserted each run), plus one small JSON snapshot per subscription per run
(purged by `ACD_RETENTION_MONTHS`).
