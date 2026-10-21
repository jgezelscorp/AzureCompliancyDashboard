# Operations runbook

Portable operations for the Compose deployment (and, with adaptation, any container platform). Placeholders only: never commit real tenant/subscription IDs or secrets.

## Topology

| Service | Role | Health |
|---|---|---|
| `postgres` | PostgreSQL 16, volume `pgdata`, not published to the host | `pg_isready` |
| `migrate` | one-shot `alembic upgrade head`, must succeed before API/worker start | exit code |
| `backend` | FastAPI API (`127.0.0.1:8000`) | `/readyz` |
| `worker` | `python -m app.collectors`: collection scheduler **and** export-artifact purge loop | process / logs |
| `frontend` | nginx (unprivileged) serving the SPA, proxies `/api` | HTTP 200 on `/` |

Hardening in `docker-compose.yml`: non-root users, `read_only` root filesystems (+ tmpfs `/tmp`), `cap_drop: ALL`, `no-new-privileges`, memory/CPU/pid limits, bounded json-file logs, loopback-only published ports. Images contain no secrets; `POSTGRES_PASSWORD` and `ACD_AUTH_API_CLIENT_SECRET` come only from the runtime environment or an untracked `.env`.

## Health endpoints

- `GET /healthz`: liveness, no dependencies. Always 200 while the process runs.
- `GET /readyz`: readiness, executes `SELECT 1`; **503** when the database is unreachable. Use it for load-balancer/orchestrator readiness, not liveness (a DB outage should not restart the API).

## Hardening behaviour

- **Security headers** on every API response (`nosniff`, `X-Frame-Options: DENY`, `no-referrer`, CSP `default-src 'none'`, `Cache-Control: no-store`, HSTS in `production`). nginx sets equivalent headers plus a SPA CSP allowing `connect-src` to `https://login.microsoftonline.com` (PKCE token endpoint). If you host the SPA elsewhere, carry these headers over. Terminate TLS in front of nginx.
- **CORS** is an explicit allowlist (`ACD_CORS_ORIGINS`); `*` is rejected in production; only `GET`/`POST` and `Authorization`/`Content-Type` headers.
- **Rate limiting** (`ACD_RATE_LIMIT_PER_MINUTE`, default 600, `0` disables): per-client sliding window returning `429` + `Retry-After`; health endpoints exempt. It is in-process and keyed on the TCP peer address, so behind nginx/an ingress all users share one key and N replicas multiply the limit. Treat it as a safety net and enforce real limits at the edge (WAF / API gateway).
- **Azure RBAC permission cache**: `has_action` results are cached 60 s per (token digest, scope, action). Only definitive allow/deny answers are cached; ARM errors, malformed or paged-incomplete answers return deny and are *not* cached (fail closed). Raw tokens are never stored. A revoked role is therefore honoured within about a minute.
- **Logging**: JSON lines to stdout (`ACD_LOG_LEVEL`). Bearer tokens, JWTs, `password=`/`secret=`/`token=` pairs, DB URL passwords and sensitive extra fields are redacted. Every request gets an `X-Request-ID` and an access log line (method, path, status, duration; no query string, no body).
- **Export purge**: the worker runs `purge_expired()` every `ACD_EXPORT_PURGE_INTERVAL_MINUTES` (default 5) so expired artifacts are removed even when nobody calls the API.

## Configuration

See `.env.example`. New in this work: `ACD_RATE_LIMIT_PER_MINUTE`, `ACD_LOG_LEVEL`, `ACD_EXPORT_PURGE_INTERVAL_MINUTES`.

## Start, stop, upgrade

```
docker compose up -d --build
docker compose ps                      # postgres/backend/frontend should be "healthy"
docker compose logs -f worker backend
docker compose down                    # keeps the pgdata volume
```

Upgrade: pull/build new images, then `docker compose up -d --build`. The `migrate` service applies migrations first. Migrations are forward-only in practice: **take a backup before upgrading** (below). Current chain: `0001` core tables, `0002` collection history, `0003` onboarded scopes, `0004` export jobs/audit, `0005` logs outbox.

Preview SQL without applying: `docker compose run --rm migrate alembic upgrade head --sql`.
Roll back one step (only if the migration defines `downgrade`): `docker compose run --rm migrate alembic downgrade -1`. Prefer restoring the pre-upgrade backup.

## Backup and restore

Backup (logical, consistent, safe while running):

```
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > acd-backup.dump
```

Restore into an empty database (stop writers first):

```
docker compose stop backend worker
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < acd-backup.dump
docker compose run --rm migrate alembic upgrade head   # no-op when the dump is current
docker compose up -d
```

Notes: store dumps encrypted and off-host; they contain compliance evidence and audit events. Schedule backups (cron / Task Scheduler / managed-database PITR on a platform service) and **test a restore regularly**. Retention of data inside the database is governed by `ACD_RETENTION_MONTHS`.

## Migration verification checklist

1. Fresh database: `alembic upgrade head` succeeds through `0005`.
2. `alembic current` shows `0005`; `alembic upgrade head` again is a no-op.
3. `GET /readyz` returns 200, `GET /api/v1/info` responds.
4. Restore drill: restore last backup into a scratch database and run step 1-3.

## Azure Container Apps (consumption)

`infra/bicep/containerapps/main.bicep` deploys: user-assigned identities (`<prefix>-api-id`, `<prefix>-collector-id`), ACR Basic (admin user off, `AcrPull` for the identities), a VNet, PostgreSQL Flexible Server 16 Burstable with **private access only**, a Container Apps environment (workload-profiles, Consumption) logging to an existing Log Analytics workspace, a manual migration Job, an internal API app, one worker and the public web app (TLS, optional `webAllowedCidrs`). It is not deployed by CI; CI only runs `az bicep build`. Always `what-if` first.

Two phases (`deployApps`):

1. `az deployment group what-if|create -g <rg> -f infra/bicep/containerapps/main.bicep -p deployApps=false logAnalyticsWorkspaceName=<law> pgAdminPassword=<generated, alphanumeric>` (the database URL is built in the template and kept only as a Container Apps secret; Key Vault is not used because tenant policy may disable its public access).
2. Build images: `az acr build -r <acr> -t acd-backend:<tag> backend` and `az acr build -r <acr> -t acd-frontend:<tag> --build-arg BACKEND_UPSTREAM=http://<prefix>-api frontend` (the web nginx proxies `/api` to the internal API app by name).
3. Create the Entra app registrations, pass the API client secret as the secure parameter `apiClientSecret` (the OBO exchange needs a secret; it becomes a Container Apps secret and is never in the repo or logs), and rerun the deployment with `deployApps=true backendImage=... frontendImage=... tenantId=... subscriptionIds=... authApiClientId=... authSpaClientId=...`.
4. Run the migration job: `az containerapp job start -g <rg> -n <prefix>-migrate`, check the execution succeeded, then verify `/healthz` and `/readyz`.
5. Grant the collector identity (`collectorPrincipalId` output) read access with `infra/bicep/containerapps/rbac-subscription.bicep` (Reader; it already includes Policy Insights and guest configuration reads) and, if the history sink is used, Monitoring Metrics Publisher on the DCR (`ingestionPrincipalObjectId` of `infra/bicep/reporting`).

Notes: the public web app is the only public endpoint; the in-process rate limiter is a safety net, put WAF/edge limits in front for production. The internal API ingress allows plain HTTP because it is reachable only inside the environment. PostgreSQL has PITR backups (7 days); see the backup section for logical dumps (run them from a job inside the VNet).


## Troubleshooting

- API unhealthy, `/readyz` 503: check `docker compose logs postgres`, then the `ACD_DATABASE_URL` host/password.
- `migrate` exits non-zero: read `docker compose logs migrate`; fix and re-run `docker compose up -d`.
- Spurious 429s behind a proxy: raise `ACD_RATE_LIMIT_PER_MINUTE` or move limiting to the edge (shared peer address).
- Exports stuck as expired: confirm the `worker` container is running (it hosts the purge loop).
