# Azure Compliancy Dashboard

Read-only reporting on Azure Policy and Azure Machine Configuration (Windows Azure Security Baseline and CIS Windows Server benchmark) for Azure VMs and Azure Arc-enabled servers.

Two deliverables:

1. **Azure Workbook** with deployable Bicep, drilling down from estate to individual check.
2. **Standalone web app** (React/TypeScript, FastAPI, PostgreSQL, Docker Compose) with history, scheduled collection and CSV/PDF export.

Status: work in progress. Tracked via issues I01-I12. Tenant and subscription IDs are configuration and are never hardcoded. No secrets belong in this repository.
