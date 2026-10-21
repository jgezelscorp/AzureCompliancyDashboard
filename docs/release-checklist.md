# Release and customer-deployment checklist

Nothing here has been done yet. Every box is open until someone does it against a real tenant and records the evidence. Use placeholder IDs (`00000000-0000-0000-0000-000000000000`) in any shared notes.

Read [known-limitations.md](known-limitations.md) first; this checklist is how those items get closed.

## A. Pre-release (repository)

- [ ] CI green on the release commit (secret scan, fixtures, backend ruff/mypy/pytest incl. heavy, frontend, workbook/Bicep checks).
- [ ] No tenant/subscription IDs, customer names or secrets in the tree or history (`git grep` for GUIDs; only the all-zero placeholder is allowed).
- [ ] Docker images built from clean checkout (`docker compose build`), then `docker compose up` smoke test: `/healthz`, `/readyz`, `/api/v1/info`, SPA loads.
- [ ] Alembic `0001`-`0005` run on a real PostgreSQL 16 (`upgrade head`, then `downgrade`/restore test from backup).
- [ ] Nginx CSP and security headers exercised in a real browser (no console violations, MSAL sign-in works).
- [ ] Licence chosen by the owner and a LICENSE file added (none yet). Do not publish releases before this.
- [ ] Resolve every `verified: false` entry in `contracts/permissions-manifest.json` (currently three) and update the flag with evidence.
- [ ] Mark each unverified item in [known-limitations.md](known-limitations.md) as verified, fixed, or still open.

## B. Live validation (test tenant, read-only)

Use a non-production subscription with at least one Windows Azure VM and one Arc-enabled server, with the Azure Windows baseline and CIS Windows Server guest configuration assigned.

- [ ] Run each Resource Graph query in `workbooks/queries/` in Resource Graph Explorer; confirm table and column names, and that `latestAssignmentReport.endTime` is projected (else everything is UnknownAge).
- [ ] Compare workbook output with the Python reference model (`scripts/metrics_reference.py`) on the same data; parity is not proven with real KQL.
- [ ] Render the workbook in the portal (all tabs, drilldowns, check keys with unusual characters, conditional visibility, History tab).
- [ ] Confirm `AzureBaselineDefinitionId` (default: built-in Azure compute security baseline) matches your assignments and the policy rows are labelled.
- [ ] Collector: Policy Insights `api-version` (currently 2024-10-01), guest configuration versions, exemption handling, eligibility (currently OS type only).
- [ ] Replace synthetic CIS fixtures with captured, sanitised live output; add live-evidence tests.
- [ ] Sign-in: SPA PKCE flow, API token validation, viewer at subscription scope, and the RG-only viewer (known 403).
- [ ] RBAC: `Microsoft.Authorization/permissions` behaviour with deny assignments, conditions and PIM-eligible roles.
- [ ] Logs Ingestion (if enabled): API version, token scope, DCR kind, required roles on DCR and workspace; verify delivery, no duplicate rows on retry, History tab queries.
- [ ] Exports: generate CSV/PDF, check scope disclosures and purge after TTL.
- [ ] Accessibility: colour contrast and keyboard checks on app and workbook.

## C. Approvals and RBAC needed (customer)

Nothing has been created. A customer will need approvals for:

- [ ] Entra app registrations: one API (exposed scope) and one SPA (redirect URIs); admin consent per [auth-and-onboarding.md](auth-and-onboarding.md). Secrets only in the runtime environment or Key Vault.
- [ ] Collector identity (managed identity, service principal or workload identity) with **read-only** roles at the onboarded scopes (Reader plus guest-configuration/policy read as listed in the permissions manifest).
- [ ] Viewer roles for end users at subscription scope (the app checks the user's own Azure RBAC).
- [ ] Workbook users: Reader on the target scope; Log Analytics Reader on the workspace for the History tab.
- [ ] If history mode is used: workspace, DCR and Monitoring Metrics Publisher (or equivalent) for the writer, after verification.
- [ ] Hosting: Container Apps or VM, PostgreSQL, ingress/WAF, DNS/TLS, security review and change approval.

## D. Deployment (customer)

- [ ] `az deployment group what-if` on every Bicep template (`infra/bicep/workbook`, `infra/bicep/reporting`, `infra/bicep/containerapps`); review output with the customer; nothing is applied without approval.
- [ ] Deploy to a staging resource group first.
- [ ] Run the Container Apps migration job (`az containerapp job start`) before starting or upgrading the API and worker.
- [ ] Take a database backup before every upgrade ([operations.md](operations.md)).
- [ ] Put WAF/edge rate limiting in front of ingress (in-process limiter is only a safety net).
- [ ] Confirm collection ran, freshness shown, and the app output matches the workbook for the same scope.
- [ ] Record the evidence (dates, versions, commit SHA) in the release notes.

## E. Rollback

- Workbook: redeploy the previous template version or delete the shared workbook resource; it holds no data.
- App: redeploy the previous image tag. Migrations are forward-only in practice, so restore the pre-upgrade database backup if the schema changed.
- Log Analytics: stop the sink (`ACD_LOGS_SINK_ENABLED=false`); the app and workbook keep working. Tables/DCR can be removed by deleting the reporting deployment's resources.
- Entra: remove consent, delete or disable the app registrations and collector role assignments.
- Verify the rollback with `/readyz`, a manual collection, and the workbook overview.

## Explicit non-claims

This project makes no certification, audit-readiness or compliance-attestation claim. Output is evidence from Azure Policy and Machine Configuration reports and is only as good as those reports.
