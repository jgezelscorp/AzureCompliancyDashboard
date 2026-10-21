# Enhanced / history mode: Log Analytics (I08)

Optional. The app (PostgreSQL + API) and the live workbook (Azure Resource Graph) each work on their own. This mode adds a fleet-wide **history** in a Log Analytics workspace, written by the collector and read by the workbook **History / Enhanced** tab. Nothing here is deployed by CI.

| Mode | Needs | Unaffected by |
|---|---|---|
| App only | PostgreSQL | Workspace, DCR, sink off by default |
| Workbook only | `infra/bicep/workbook` | Collector, workspace |
| Enhanced | Workspace + tables + DCR (`infra/bicep/reporting`), `ACD_LOGS_*` on the collector, a workspace selected in the workbook | |

## Tables

Source of truth: `contracts/logs-schema.json` (copy for packaging: `backend/app/sink/logs-schema.json`; a test asserts they are identical). Bicep, the row mapper and the validator all read it.

| Table | Rows |
|---|---|
| `ComplianceCollectionRuns_CL` | One per run, including failed/partial runs |
| `PolicyComplianceSnapshots_CL` | One per run and family: the three metrics, never blended |
| `MachineConfigReports_CL` | One per report newly stored by the run |
| `MachineConfigChecks_CL` | One per check of those reports. Reasons are kept as phrase + code only (max 20), never counted as checks |

Common columns: `TimeGenerated` (= run start, the snapshot time), `RecordKey` (deterministic hash), `SchemaVersion`, `SentAt`, `RunId`. **Delivery lag = `ingestion_time() - TimeGenerated`.** The Logs Ingestion API is not idempotent, so a retry can duplicate rows; every query de-duplicates on `RecordKey` / `(ReportId, CheckKey)`.

No error text, token, tenant ID or credential is exported. Machine and resource-group names are exported (they are evidence); treat the workspace as holding the same sensitivity as the PostgreSQL data.

## Deploy (operator action)

```powershell
az deployment group what-if -g <rg> -f infra/bicep/reporting/main.bicep -p infra/bicep/reporting/main.example.bicepparam
```

Review, then `create`. Parameters: `createWorkspace` (false references an existing workspace in `existingWorkspaceResourceGroup`), `retentionDays` (minimum 30, default 400 = 13 months plus margin; 397 is the smallest value that covers 13 months, interactive Analytics plan so history stays queryable), `dailyQuotaGb` (daily ingestion cap for a new workspace, -1 = none), `deployDataCollectionEndpoint` (false: a `Direct` DCR exposes its own ingestion endpoint; set true only if your design needs a DCE), `ingestionPrincipalObjectId` (optional Monitoring Metrics Publisher assignment on the DCR; leave empty to assign nothing). Outputs: `dcrImmutableId` and `ingestionEndpoint`.

Separate the roles: the collector identity gets only ingestion on the DCR; viewers get **Log Analytics Reader** on the workspace (or table-level RBAC); deployers need rights to create the resources. Create and grant them yourself; this repository creates no app registrations.

**Retention note:** the 13-month history goal needs `retentionDays` >= 397. A deployment that sets `retentionDays = 30` (for example to save cost) limits the workbook History tab to about the last 30 days regardless of the TimeRange parameter; the app's PostgreSQL history (`ACD_RETENTION_MONTHS`) is unaffected.

Cost: ingestion and 400-day retention are billed by Log Analytics. A run writes roughly one report row per machine and family plus one row per check; use a workspace you are happy to bill for it.

## Collector configuration

| Variable | Meaning |
|---|---|
| `ACD_LOGS_SINK_ENABLED` | `true` to enable (default `false`) |
| `ACD_LOGS_INGESTION_ENDPOINT` | `https://<name>.<region>.ingest.monitor.azure.com` only (validated, no path/credentials) |
| `ACD_LOGS_DCR_IMMUTABLE_ID` | `dcr-` + 32 hex characters |
| `ACD_LOGS_BATCH_MAX_BYTES`, `_MAX_RECORDS`, `_MAX_ATTEMPTS`, `_RETRY_MAX_MINUTES`, `_DELIVERED_KEEP_DAYS`, `_MAX_RECORDS_PER_DRAIN` | Batch size, retry and housekeeping limits |

The collector uses its managed identity or developer credential with scope `https://monitor.azure.com//.default`.

## Delivery behavior

- After a run is committed, rows are written to the `logs_outbox` table (migration 0005), idempotent on `(stream, RecordKey)`, and delivered in batches. **PostgreSQL is the system of record; a Logs outage never changes run status, metrics or evidence.**
- Transient failures (401/403 until RBAC propagates, 408/429, 5xx, network, token) retry inline with backoff, honouring `Retry-After`, then are rescheduled; later runs drain the backlog. After `ACD_LOGS_MAX_ATTEMPTS` rows are marked dead (kept for diagnosis, purged later).
- 400/413 batches are bisected so one bad row cannot block the rest; only the rejected row is marked dead.
- `GET /api/v1/collection/sink` shows `enabled`, counts, oldest pending age and a state (`ok`, `backlog`, `degraded`). No payloads or remote error text.
- **No backfill.** Only reports stored after the sink is enabled are sent. The History tab therefore can show machines as stale or missing that the app knows. Gaps from outages stay gaps in the workbook until the backlog drains.

## Workbook History tab

Select a **Workspace** in the workbook parameters (the picker lists workspaces you can read). Items: collection runs with delivery lag, snapshot trend per family (measures kept separate), fleet-wide categories with drill-down to checks, daily failure distribution by category, and drift (regressions/recoveries). History freshness is measured against the latest stored run snapshot, not now, and the tab says so. Queries read only the four tables; the validator enforces this and that live (Resource Graph) queries never read them.

## Validate locally

```powershell
python scripts/build_workbook.py --check
python scripts/validate_workbook.py --bicep   # also builds infra/bicep/reporting
pytest tests/workbook
cd backend; pytest; ruff check .; mypy .
```

## Caveats and unverified items

Nothing was deployed or run against Azure. The KQL was never executed; the parity model proves the logic only.

- Logs Ingestion API version `2023-01-01`, the token scope, the 400/413 semantics and the exact RBAC roles (`Monitoring Metrics Publisher` on the DCR) are from documentation and unverified (see `contracts/source-manifest.json`).
- `Direct` DCR kind, `Microsoft.Insights/dataCollectionRules@2023-03-11`, table API `2022-10-01` and the DCR/workspace region and cross-resource-group behavior were checked only by `bicep build`.
- Late data: ingesting rows whose `TimeGenerated` is old (long outages) may be limited or dropped by the service; this limit is unverified. The outbox keeps retrying until attempts are exhausted.
- Portal rendering of `conditionalVisibilities`, `timeContextFromParameter` and the optional type-5 workspace parameter is unverified.
- The Subscriptions / Resource groups parameters do not scope the History tab, and workspace filters are not authorization. Anyone with workspace read access sees all exported history.
- Duplicate rows are possible on retry; queries de-duplicate, but raw table counts can be higher.
- Schema changes need a new `schemaVersion`, table update and DCR update together; no migration tooling is provided for existing tables.
