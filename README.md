# Azure Compliancy Dashboard

Read-only reporting on Azure Policy and Azure Machine Configuration (Windows Azure Security Baseline and CIS Windows Server benchmark) for Azure VMs and Azure Arc-enabled servers.

Two deliverables:

1. **Azure Workbook** with deployable Bicep, drilling down from estate to individual check.
2. **Standalone web app** (React/TypeScript, FastAPI, PostgreSQL, Docker Compose) with history, scheduled collection and CSV/PDF export.

Status: work in progress. Tracked via issues I01-I12. Tenant and subscription IDs are configuration and are never hardcoded. No secrets belong in this repository.

## Local development

Prerequisites: Python 3.11, Node 24, Docker (optional).

**Everything via Docker Compose**

```
copy .env.example .env      # placeholders only; set a local POSTGRES_PASSWORD
docker compose up --build
```

Frontend: http://localhost:8080, API: http://localhost:8000 (`/healthz`, `/api/v1/info`, docs at `/docs`). The backend applies Alembic migrations on start.

**Backend** (`backend/`)

```
cd backend
python -m venv .venv ; .venv\Scripts\activate
pip install -e ".[dev]"
ruff check . ; mypy . ; pytest
uvicorn app.main:app --reload
```

Configuration comes from `ACD_*` environment variables (see `.env.example`) and is validated at startup. Migrations: `alembic upgrade head` (or `alembic upgrade head --sql` to preview).

**Frontend** (`frontend/`)

```
cd frontend
npm ci
npm run lint ; npm run typecheck ; npm test ; npm run build
npm run dev
```

**Fixtures**: `pip install jsonschema` then `python scripts/validate_fixtures.py`.

**Workbook** (`workbooks/`): see `docs/workbook.md`. `python scripts/validate_workbook.py --bicep` and `pytest tests/workbook`.


