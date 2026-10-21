# Known limitations and unverified assumptions

Honest, consolidated list. **Nothing has been deployed to Azure, no app registrations have been created, no live tenant has been used, no certification is claimed, and no license has been chosen.** "Unverified" means taken from documentation or samples and never exercised live. Close items via [release-checklist.md](release-checklist.md).

## I04 Permissions and RBAC

- Three entries in `contracts/permissions-manifest.json` have `verified: false` (guest configuration assignments read, `Microsoft.Authorization/permissions` at subscription scope, subscriptions list).
- How the permissions API reports deny assignments, role-assignment conditions and PIM-eligible roles is unproven.

## I05 Collectors

- Policy Insights `api-version` 2024-10-01 is unverified.
- Policy exemptions are not collected.
- Eligibility is derived from OS type only.
- CIS fixtures are synthetic; there are no live tests.

## I06 Auth and onboarding

- The editable settings view is **not implemented**.
- A viewer with RG-level-only roles gets 403 (subscription scope is required).
- PKCE sign-in has never been tried on a real tenant.

## I07 Workbook

- ARG table and column names are unverified live. If `latestAssignmentReport.endTime` is not projected, all reports show UnknownAge (never green).
- The workbook has never been rendered in the portal.
- `AzureBaselineDefinitionId` is a placeholder and must be set, otherwise no policy row is labelled AzureWindowsBaseline.
- Check keys containing a single quote break the drilldown.

## I08 Log Analytics reporting

- Logs Ingestion API version, token scope, required roles and the Direct DCR kind are unverified.
- Workbook `conditionalVisibilities` rendering is unverified.
- The Subscriptions and Resource groups parameters do not filter the History tab.
- No backfill of past data.
- Retries can duplicate rows.

## I09 Exports

- Artifacts are stored in the database and generated synchronously (bounded; no async worker).
- Migration `0004` has only been checked as offline SQL.
- PDFs are plain text, not designed documents.

## I10 Workbook quality

- Parity between workbook and the Python model is not proven with real KQL.
- No colour-contrast checks were done.

## I11 Packaging and hardening

- Docker images have never been built.
- Alembic `0001`-`0005` have never run on a live PostgreSQL.
- The in-process rate limiter is keyed on the TCP peer address: behind nginx/ingress all users share one key, and replicas multiply the limit.
- The Azure RBAC permission cache lasts 60 s, so a revoked role is honoured within about a minute.
- The Container Apps template has no migration job.
- The nginx CSP has not been tested in a browser.

## Project-level

- No license chosen; do not redistribute as open source until the owner decides.
- No certification or compliance-attestation claim of any kind.
- Output is only as reliable as the underlying Azure Policy / Machine Configuration reports and their freshness.
