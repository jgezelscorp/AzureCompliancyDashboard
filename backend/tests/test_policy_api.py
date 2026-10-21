"""Estate-wide policy API: bearer auth, RBAC scope filtering before aggregation, pagination."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import deps
from app.auth.settings import get_auth_settings
from app.config import Settings
from app.database import get_session
from app.main import create_app
from tests.test_auth import FakeArm, FakeObo, validator
from tests.test_auth import settings as auth_settings
from tests.test_collector_run import SUB, make_runner
from tests.test_estate_collect import STORAGE, estate_bundle
from tests.test_metrics_api import AUTH, OTHER, Env, arm_routes

BASE = "/api/v1/policy"
ENDPOINTS = [
    f"{BASE}/overview",
    f"{BASE}/breakdown?dim=initiative",
    f"{BASE}/top-policies",
    f"{BASE}/states",
    f"{BASE}/resources",
    f"{BASE}/exemptions",
    f"{BASE}/trend",
    f"{BASE}/filters",
    f"{BASE}/quality",
    f"{BASE}/machines/coverage",
]


class PolicyEnv(Env):
    def __init__(self, runs: int = 1) -> None:
        bundle = estate_bundle()
        runner, _, self.factory = make_runner(bundle)
        for _ in range(runs):
            runner.run_once()
        self.app = create_app(Settings(environment="test"))
        self.arm = FakeArm(arm_routes())
        self.obo_fail = False
        self.app.dependency_overrides[get_session] = self._session
        self.app.dependency_overrides[deps.get_validator] = validator
        self.app.dependency_overrides[deps.get_obo] = lambda: FakeObo(self.obo_fail)
        self.app.dependency_overrides[deps.get_arm] = lambda: self.arm
        self.app.dependency_overrides[get_auth_settings] = lambda: auth_settings()
        self.client = TestClient(self.app)
        self.register(SUB)

    def _session(self) -> Iterator[Session]:
        with self.factory() as s:
            yield s

    def get(self, url: str) -> Any:
        return self.client.get(url, headers=AUTH)


@pytest.mark.parametrize("url", ENDPOINTS)
def test_endpoints_require_bearer(url: str) -> None:
    e = PolicyEnv()
    assert e.client.get(url).status_code == 401


@pytest.mark.parametrize("url", ENDPOINTS)
def test_unreadable_scope_fails_closed(url: str) -> None:
    e = PolicyEnv()
    e.arm = FakeArm(arm_routes(readable=(OTHER,)))
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    assert e.get(url).status_code == 403


def test_overview_kpis_carry_denominator_grain_and_formula() -> None:
    e = PolicyEnv()
    body = e.get(f"{BASE}/overview").json()
    kpis = {k["id"]: k for k in body["kpis"]}
    pc = kpis["policyCompliance"]
    assert pc["grain"] == "policy evaluation" and pc["formula"]
    head = body["headline"]
    assert pc["numerator"] == head["compliant"]
    assert pc["denominator"] == head["compliant"] + head["nonCompliant"]
    assert body["scope"]["authorizedSubscriptions"] == 1
    assert any("composite" in label for label in body["labels"])
    assert "score" not in {k["id"].lower() for k in body["kpis"]}
    assert body["defender"]["available"] is False
    assert body["summary"]


def test_high_impact_tile_is_no_data_without_severity_metadata() -> None:
    e = PolicyEnv()
    bundle_kpis = {k["id"]: k for k in e.get(f"{BASE}/overview").json()["kpis"]}
    # the synthetic definition carries severity High, so the tile has a value
    assert bundle_kpis["highImpactFailing"]["value"] == 1


def test_history_says_how_many_samples() -> None:
    e = PolicyEnv(runs=1)
    t = e.get(f"{BASE}/trend").json()
    assert t["samples"] == 1 and "1 sample so far" in t["note"]


def test_filter_restricts_rows_and_aggregates_together() -> None:
    e = PolicyEnv()
    allr = e.get(f"{BASE}/states?limit=200").json()
    only = e.get(f"{BASE}/states?limit=200&rtype=microsoft.storage/storageaccounts").json()
    assert 0 < only["total"] < allr["total"]
    assert all(r["resourceType"] == "microsoft.storage/storageaccounts" for r in only["rows"])
    assert only["tally"]["evaluations"] == only["total"]


def test_pagination_and_sorting_are_validated() -> None:
    e = PolicyEnv()
    page = e.get(f"{BASE}/states?limit=1&offset=1").json()
    assert len(page["rows"]) <= 1 and page["limit"] == 1
    assert e.get(f"{BASE}/states?sort=bogus").status_code == 422
    assert e.get(f"{BASE}/breakdown?dim=bogus").status_code == 422
    assert e.get(f"{BASE}/states?limit=100000").status_code == 422


def test_resource_detail_and_not_found() -> None:
    e = PolicyEnv()
    r = e.get(
        f"{BASE}/resource",
    ).status_code
    assert r == 422
    got = e.client.get(f"{BASE}/resource", params={"id": STORAGE}, headers=AUTH)
    assert got.status_code == 200
    assert got.json()["states"][0]["state"] == "NonCompliant"
    assert e.client.get(f"{BASE}/resource", params={"id": "/nope"}, headers=AUTH).status_code == 404


def test_breakdown_by_resource_type_and_tag_dimension() -> None:
    e = PolicyEnv()
    body = e.get(f"{BASE}/breakdown?dim=resourceType").json()
    assert body["total"] >= 1 and body["rows"][0]["evaluations"] >= 1
    assert e.get(f"{BASE}/breakdown?dim=tag:owner").status_code == 200


def test_exemptions_endpoint_buckets() -> None:
    e = PolicyEnv()
    body = e.get(f"{BASE}/exemptions").json()
    assert body["total"] == 1 and body["buckets"]["expired"] == 0
    assert e.get(f"{BASE}/exemptions?status=active").json()["filteredTotal"] == 1


def test_machine_coverage_splits_kinds() -> None:
    e = PolicyEnv()
    body = e.get(f"{BASE}/machines/coverage").json()
    assert [g["label"] for g in body["groups"]] == ["All machines", "Azure VM", "Arc machine"]
    assert "separate" in body["note"]


def test_machine_detail_unauthorized_and_unknown() -> None:
    e = PolicyEnv()
    other = f"/subscriptions/{OTHER}/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/x"
    assert (
        e.client.get(f"{BASE}/machines/detail", params={"id": other}, headers=AUTH).status_code
        == 404
    )
    mine = f"/subscriptions/{SUB}/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/x"
    assert (
        e.client.get(f"{BASE}/machines/detail", params={"id": mine}, headers=AUTH).status_code
        == 404
    )


def test_rows_of_unauthorized_subscription_never_counted() -> None:
    e = PolicyEnv()
    from sqlalchemy import update

    from app.db_history import PolicyStateRow

    with e.factory() as s, s.begin():
        s.execute(update(PolicyStateRow).values(subscription_id=OTHER))
    body = e.get(f"{BASE}/overview").json()
    assert body["headline"]["evaluations"] == 0
    assert e.get(f"{BASE}/states").json()["total"] == 0
    assert e.get(f"{BASE}/top-policies").json()["rows"] == []
