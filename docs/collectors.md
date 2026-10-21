# Collectors

The collector reads Azure state through Azure Resource Manager (ARM) and writes evidence to the database. The API then serves metrics from that evidence.

## Read-only allowlist

`backend/app/azure/allowlist.py` mirrors `contracts/source-manifest.json`. Default action is deny.

- Only allowlisted host, method, path template and pinned `api-version` combinations are permitted.
- POST is allowed only for the read-style query operations listed in the manifest.
- `nextLink` continuation URLs are validated before any credential is attached. They must use https, carry no userinfo or port, and keep the host, path and api-version of the originating request. They must also stay inside the selected subscriptions.

## Client behavior

`backend/app/azure/client.py` retries 408, 429, 500, 502, 503 and 504 with exponential backoff and jitter. It honours `Retry-After` on 429. It follows paging via validated `nextLink`. Tokens are never logged.

## Persistence

Evidence and snapshot tables are created by migrations 0001 and 0002. Migration 0003 adds `onboarded_scopes` (subscription id, registered by, registered at). The first registrant of a subscription wins and ids are stored lowercase.

## Metrics endpoint authorization

Every `/api/v1/metrics/*` and `/api/v1/collection/*` endpoint needs an Entra bearer token. A viewer sees only subscriptions that are registered, visible to the viewer in ARM and readable by the viewer through Azure RBAC. If subscriptions are registered but none is authorized, or ARM cannot be queried, the API returns 403 (fail closed). If nothing is registered it returns empty data. A `subscriptionId` query parameter can only narrow the scope.

- `/metrics/latest` is recomputed from the evidence of the viewer's authorized machines.
- Only Fresh reports are counted. Stale, unknown-age, missing and unknown-applicability machines are excluded from pass rates and reported as coverage gaps.
- `/metrics/history` includes collector-wide aggregates only when the viewer is authorized for every configured subscription; otherwise it returns only a machine summary.
- `/collection/runs` omits error text and checkpoints.

## Optional Log Analytics sink

Off by default (`ACD_LOGS_SINK_ENABLED`). When enabled, after each run is committed to PostgreSQL the collector queues rows in the `logs_outbox` table (migration 0004) and delivers them with the Logs Ingestion API. A sink outage, throttling or token failure never changes run status or evidence; the data is kept in the outbox and retried. See `docs/logs-reporting.md`. `GET /api/v1/collection/sink` returns counts and ages only.

## Caveats

- Authorization is assessed at subscription level. A viewer with access only at resource-group level receives 403.
- ARM permission checks are made on each request with no caching.
- The Windows baseline and CIS families are always reported separately. CIS data from the fixtures is synthetic, not live, and is not a certification.
