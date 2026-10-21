# Policy estate API (`/api/v1/policy`)

All endpoints require an Entra bearer token. Rows are loaded **filtered to the caller's
RBAC-authorized subscriptions in SQL before any aggregation**; an unreadable scope returns 403 and an
unauthorized resource id returns 404. Responses are gzipped; list endpoints take `limit` (max 500)
and `offset`.

Common filters (query params): `sub, rg, loc, rtype, initiative, assignment, definition, state,
category, effect, severity, tag (key=value), maxAgeHours, minAgeHours, q`.

| Endpoint | Purpose |
|----------|---------|
| `GET /overview` | KPI tiles (value, numerator, denominator, grain, formula, drill link, previous, delta, sparkline), headline, facts-only summary, samples, Defender availability, machine KPIs, labels |
| `GET /breakdown?dim=` | Compliance by `initiative`, `assignment`, `category`, `resourceType`, `subscription`, `resourceGroup`, `location`, `tag:<key>`; sortable and paginated |
| `GET /top-policies` | Top non-compliant policy definitions with affected-resource counts |
| `GET /states` | Policy states (paginated, sortable) with tally of the filtered rows |
| `GET /resources`, `GET /resource?id=` | Non-compliant resources and drill-down to their policy states |
| `GET /exemptions` | Exemptions with buckets (expired, <30, 30-59, 60-89 days) |
| `GET /trend` | Series from `estate_snapshots`, gap flags (interval > 2x collection interval), `samples` and note |
| `GET /filters` | Distinct filter values for the explorer |
| `GET /quality` | Freshness and evidence limits (what we cannot see) |
| `GET /machines/coverage` | All / Azure VM / Arc: eligible, assigned, reported, fresh (kept apart from compliance %) |
| `GET /machines/detail?id=` | Guest assignments, reports, checks by derived category, policy states, history |

Metric definitions are in `docs/policy-estate.md`. There is no composite risk score; every KPI
states its denominator and grain.

Diagnostics: `python -m app.tools.dbcounts` prints table row counts only (read-only).
