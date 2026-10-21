# Authorized exports (I09)

CSV and PDF exports are bounded jobs under `/api/v1/exports`. They add no new data path: an export is
rendered from the same newest snapshot and the same authorized-scope filtering as the UI
(`_authorized_bundle`, built on a fresh delegated Azure RBAC check).

| Endpoint | Purpose | Authorization |
|---|---|---|
| `POST /api/v1/exports` | Create a job (`format` csv/pdf, `family`, `template` executive/technical, `dataset` checks/machines, optional `subscriptionId`) | Bearer + fresh OBO/RBAC scope check; a scope filter outside the viewer's scopes is 403 and audited |
| `GET /api/v1/exports`, `GET /api/v1/exports/{id}` | Own job status only (other users get 404) | Bearer |
| `GET /api/v1/exports/{id}/download` | Artifact bytes | Bearer + **fresh** scope check; every subscription the job was created with must still be authorized, otherwise 403 |

- **No public links.** Downloads need the bearer token; the UI fetches a blob and saves it locally.
  Responses are `Cache-Control: no-store`, `nosniff`, `attachment`.
- **Lifecycle.** Artifacts live 15 minutes (`ARTIFACT_TTL`), then are purged (row kept as a tombstone one more
  day). Purge runs on create/list/status/download and as `purge_expired()` for schedulers. Bounds: 5,000 rows,
  5 MB, 10 active jobs per user (`MAX_*` constants in `app/api/exports.py`).
- **Audit** (`export_audit`, migration `0004`): `export.created|downloaded|denied|expired|purged` with actor oid,
  job id and short detail; never artifact content, tokens or secrets.
- **CSV safety.** Text cells starting with `= + - @ | %`, tab or CR/LF are prefixed with `'`; control characters
  are stripped. Numbers are not altered.
- **PDF safety.** A dependency-free writer emits only built-in Helvetica text: all text is escaped and
  Latin-1 filtered; there are no images, fonts, links, annotations, scripts or remote assets.
- **Disclosures** are in every artifact: scope (authorized vs onboarded, partial), snapshot time, generation time,
  freshness window and stale flag, baseline family note, synthetic-CIS caveat, no-certification statement.

Limits: artifacts are stored in the database (bounded) and generated synchronously, so "job status" is
`completed` immediately; a separate worker/object store is future work. Download re-authorization uses the
same Azure RBAC propagation/token limits as every other protected request.
