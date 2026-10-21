from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import EvidenceBundle
from tests.conftest import FIXTURES, load_fixture

FIXTURE_NAMES = sorted(p.name for p in FIXTURES.glob("*.json"))


def test_fixtures_present() -> None:
    assert len(FIXTURE_NAMES) >= 4


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_info(client: TestClient) -> None:
    body = client.get("/api/v1/info").json()
    assert body["freshnessHours"] == 24
    assert body["subscriptionCount"] == 0


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_loads_into_typed_models(name: str) -> None:
    bundle = EvidenceBundle.model_validate(load_fixture(name))
    assert bundle.synthetic is True


def test_arc_baseline_golden_counts() -> None:
    bundle = EvidenceBundle.model_validate(load_fixture("arc-azurewindowsbaseline-373.json"))
    checks = bundle.reports[0].checks
    assert len(checks) == 373
    assert len({c.check_key for c in checks}) == 373
    assert sum(c.compliance_status == "Compliant" for c in checks) == 109
    assert sum(c.compliance_status == "NonCompliant" for c in checks) == 264


def test_validate_endpoint_summarizes_fixture(client: TestClient) -> None:
    r = client.post("/api/v1/evidence/validate", json=load_fixture("cis-synthetic-mixed.json"))
    assert r.status_code == 200
    body = r.json()
    assert body["machines"] == 6
    assert body["synthetic"] is True


def test_validate_endpoint_rejects_bad_bundle(client: TestClient) -> None:
    bad = load_fixture("empty-estate.json")
    bad["machines"] = [{"machineId": "x"}]
    assert client.post("/api/v1/evidence/validate", json=bad).status_code == 422


def test_empty_estate_summary(client: TestClient) -> None:
    body = client.post(
        "/api/v1/evidence/validate", json=load_fixture("empty-estate.json")
    ).json()
    assert body["machines"] == 0 and body["checks"] == 0


def test_migration_sql_generates() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(cfg, "head", sql=True)
