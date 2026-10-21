"""Metrics/collection API: Entra bearer + Azure RBAC scope filtering (fail closed)."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.arm import ArmError
from app.auth import deps
from app.auth.permissions import VIEWER_READ_ACTIONS
from app.auth.settings import get_auth_settings
from app.config import Settings
from app.database import get_session
from app.db import MachineRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow
from app.main import create_app
from app.onboarding import OnboardingStore
from tests.conftest import load_fixture
from tests.test_auth import (
    FakeArm,
    FakeObo,
    make_token,
    perm,
    settings,
    sub_path,
    validator,
)
from tests.test_collector_run import SUB, make_runner

OTHER = "99999999-9999-9999-9999-999999999999"
AUTH = {"Authorization": f"Bearer {make_token()}"}
ENDPOINTS = [
    "/api/v1/metrics/latest",
    "/api/v1/metrics/scopes",
    "/api/v1/metrics/history",
    "/api/v1/metrics/machines?family=AzureWindowsBaseline",
    "/api/v1/metrics/categories?family=AzureWindowsBaseline",
    "/api/v1/metrics/checks?family=AzureWindowsBaseline&category=x",
    "/api/v1/metrics/checks/machines?family=AzureWindowsBaseline&checkKey=x",
    "/api/v1/collection/runs",
    "/api/v1/collection/sink",
    "/api/v1/collection/sources",
]


def arm_routes(readable: tuple[str, ...] = (SUB,)) -> dict[str, Any]:
    routes: dict[str, Any] = {
        "/subscriptions": [{"value": [{"subscriptionId": s, "displayName": "n"} for s in readable]}]
    }
    for s in readable:
        routes[sub_path(s)] = perm(list(VIEWER_READ_ACTIONS))
    return routes


class Env:
    def __init__(self, fixture: str, **settings_kw: Any) -> None:
        bundle = load_fixture(fixture)
        runner, _, self.factory = make_runner(bundle)
        runner.run_once()
        self.app = create_app(Settings(environment="test", **settings_kw))
        self.arm = FakeArm(arm_routes())
        self.obo_fail = False
        self.app.dependency_overrides[get_session] = self._session
        self.app.dependency_overrides[deps.get_validator] = validator
        self.app.dependency_overrides[deps.get_obo] = lambda: FakeObo(self.obo_fail)
        self.app.dependency_overrides[deps.get_arm] = lambda: self.arm
        self.app.dependency_overrides[get_auth_settings] = lambda: settings()
        self.client = TestClient(self.app)

    def _session(self) -> Iterator[Session]:
        with self.factory() as s:
            yield s

    def register(self, *subs: str) -> None:
        with self.factory() as s:
            store = OnboardingStore(s)
            for sub in subs:
                store.register(sub, "oid")


def env(fixture: str = "arc-azurewindowsbaseline-373.json", **kw: Any) -> Env:
    e = Env(fixture, **kw)
    e.register(SUB)
    return e


@pytest.mark.parametrize("url", ENDPOINTS)
def test_every_endpoint_requires_bearer(url: str) -> None:
    e = env()
    assert e.client.get(url).status_code == 401
    assert e.client.get(url, headers={"Authorization": "Bearer junk"}).status_code == 401


def test_latest_matches_fixture_expectations() -> None:
    e = env("cis-synthetic-mixed.json")
    body = e.client.get("/api/v1/metrics/latest", headers=AUTH).json()
    expected = load_fixture("cis-synthetic-mixed.json")["expected"]
    by = {f["family"]: f for f in body["families"]}
    for family, exp in expected.items():
        if family in by:
            assert by[family]["policyCompliance"] == exp["policyCompliance"]
            assert by[family]["checkPassRate"] == exp["checkPassRate"]
            assert by[family]["coverage"] == exp["coverage"]
    assert body["scope"] == {
        "authorizedSubscriptions": 1,
        "onboardedSubscriptions": 1,
        "partial": False,
    }
    assert any("certification" in label for label in body["labels"])


def test_no_onboarded_scopes_yields_empty_not_error() -> None:
    e = Env("arc-azurewindowsbaseline-373.json")
    body = e.client.get("/api/v1/metrics/latest", headers=AUTH).json()
    assert body["scope"]["onboardedSubscriptions"] == 0
    for f in body["families"]:
        assert f["coverage"]["eligible"] == 0 and f["checkPassRate"]["total"] == 0
    url = "/api/v1/metrics/machines?family=AzureWindowsBaseline"
    assert e.client.get(url, headers=AUTH).json()["machines"] == []


@pytest.mark.parametrize("url", ENDPOINTS[:-1])
def test_unreadable_scope_fails_closed(url: str) -> None:
    e = env()
    e.arm = FakeArm(arm_routes(readable=(OTHER,)))
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    assert e.client.get(url, headers=AUTH).status_code == 403


def test_authorization_service_error_fails_closed() -> None:
    e = env()
    e.arm = FakeArm({"/subscriptions": ArmError("boom")})
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    assert e.client.get("/api/v1/metrics/latest", headers=AUTH).status_code == 403


def test_missing_read_action_is_not_authorized() -> None:
    e = env()
    routes = arm_routes()
    routes[sub_path(SUB)] = perm(list(VIEWER_READ_ACTIONS[:-1]))
    e.app.dependency_overrides[deps.get_arm] = lambda: FakeArm(routes)
    assert e.client.get("/api/v1/metrics/latest", headers=AUTH).status_code == 403


def test_obo_failure_fails_closed() -> None:
    e = env()
    e.obo_fail = True
    assert e.client.get("/api/v1/metrics/latest", headers=AUTH).status_code == 403


def test_partial_viewer_sees_only_authorized_scope() -> None:
    e = env("cis-synthetic-mixed.json")
    e.register(OTHER)
    with e.factory() as s:
        first = s.scalars(select(MachineRow)).first()
        assert first is not None
        s.add(
            MachineRow(
                machine_id=f"/subscriptions/{OTHER}/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/hidden-vm",
                name="hidden-vm",
                kind="AzureVM",
                subscription_id=OTHER,
                resource_group="rg",
                os_type="Windows",
                eligibility="Eligible",
                last_seen_at=first.last_seen_at,
            )
        )
        snap = s.scalars(select(MetricSnapshotRow)).first()
        assert snap is not None
        s.add(
            MachineStatusSnapshotRow(
                snapshot_id=snap.id,
                machine_id=f"/subscriptions/{OTHER}/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachines/hidden-vm",
                family=snap.family,
                evidence_quality="Fresh",
                reported_state="Compliant",
                green=True,
            )
        )
        s.commit()
    body = e.client.get("/api/v1/metrics/latest", headers=AUTH).json()
    assert body["scope"]["partial"] is True and body["scope"]["authorizedSubscriptions"] == 1
    assert body["scope"]["onboardedSubscriptions"] == 2
    machines = e.client.get(
        "/api/v1/metrics/machines?family=AzureWindowsBaseline", headers=AUTH
    ).json()["machines"]
    assert all(OTHER not in m["machineId"] for m in machines)
    assert "hidden-vm" not in e.client.get("/api/v1/metrics/scopes", headers=AUTH).text
    hist = e.client.get("/api/v1/metrics/history", headers=AUTH).json()
    assert hist["aggregatesIncluded"] is False
    assert all("policyCompliance" not in p for p in hist["points"])
    assert all(p["machineSummary"]["machines"] <= 6 for p in hist["points"])
    # a subscriptionId filter cannot widen access
    denied = e.client.get(
        f"/api/v1/metrics/categories?family=AzureWindowsBaseline&subscriptionId={OTHER}",
        headers=AUTH,
    ).json()
    assert denied["categories"] == []


def test_history_aggregates_for_full_viewer() -> None:
    e = env("cis-synthetic-mixed.json")
    hist = e.client.get("/api/v1/metrics/history?family=CISWindowsSecurityBaseline", headers=AUTH)
    body = hist.json()
    assert body["aggregatesIncluded"] is True
    assert body["points"] and "checkPassRate" in body["points"][0]
    assert "not continuous" in body["samplingNote"]


def test_history_viewer_missing_collected_scope_gets_no_aggregates() -> None:
    e = env("cis-synthetic-mixed.json", subscription_ids=[SUB, OTHER])
    body = e.client.get("/api/v1/metrics/history", headers=AUTH).json()
    assert body["aggregatesIncluded"] is False


def test_drilldown_counts_reproduce_golden_373() -> None:
    e = env()
    cats = e.client.get(
        "/api/v1/metrics/categories?family=AzureWindowsBaseline", headers=AUTH
    ).json()["categories"]
    assert sum(c["total"] for c in cats) == 373
    assert sum(c["passed"] for c in cats) == 109
    cat = cats[0]["category"]
    checks = e.client.get(
        "/api/v1/metrics/checks",
        params={"family": "AzureWindowsBaseline", "category": cat},
        headers=AUTH,
    ).json()["checks"]
    assert checks and all(c["machinesPassed"] + c["machinesFailed"] == 1 for c in checks)
    machines = e.client.get(
        "/api/v1/metrics/checks/machines",
        params={"family": "AzureWindowsBaseline", "checkKey": checks[0]["checkKey"]},
        headers=AUTH,
    ).json()["machines"]
    assert len(machines) == 1 and machines[0]["name"]
    cis = e.client.get("/api/v1/metrics/categories?family=CISWindowsSecurityBaseline", headers=AUTH)
    assert cis.json()["categories"] == []


def test_scopes_breakdown_keeps_families_separate() -> None:
    e = env("dual-family-distinct.json")
    body = e.client.get("/api/v1/metrics/scopes", headers=AUTH).json()
    assert [s["subscriptionId"] for s in body["scopes"]] == [SUB]
    fams = {f["family"] for f in body["scopes"][0]["families"]}
    assert fams == {"AzureWindowsBaseline", "CISWindowsSecurityBaseline"}


def test_stale_evidence_is_never_counted_as_checks() -> None:
    e = env()
    with e.factory() as s:
        for snap in s.scalars(select(MetricSnapshotRow)):
            snap.snapshot_at = snap.snapshot_at + timedelta(days=3)
        s.commit()
    body = e.client.get("/api/v1/metrics/latest", headers=AUTH).json()
    azure = next(f for f in body["families"] if f["family"] == "AzureWindowsBaseline")
    assert azure["checkPassRate"]["total"] == 0 and azure["checkPassRate"]["percent"] is None
    assert body["dataStale"] is True
    cats = e.client.get("/api/v1/metrics/categories?family=AzureWindowsBaseline", headers=AUTH)
    assert cats.json()["categories"] == []


def test_collection_runs_omit_error_text_and_checkpoint() -> None:
    e = env()
    body = e.client.get("/api/v1/collection/runs", headers=AUTH).json()
    assert body["runs"]
    for run in body["runs"]:
        assert set(run) == {"runId", "startedAt", "finishedAt", "status", "hasError"}


def test_sources_are_the_read_only_allowlist() -> None:
    e = env()
    body = e.client.get("/api/v1/collection/sources", headers=AUTH).json()
    ids = {s["id"] for s in body["sources"]}
    assert "guestconfig-reports" in ids
    posts = [s for s in body["sources"] if s["method"] == "POST"]
    assert posts and all(s["readOnlyQueryPost"] for s in posts)


def test_no_write_routes_on_metrics_api() -> None:
    e = env()
    for route in e.app.routes:
        path = getattr(route, "path", "")
        if path.startswith(("/api/v1/metrics", "/api/v1/collection")):
            assert getattr(route, "methods", set()) <= {"GET", "HEAD"}


def test_empty_estate() -> None:
    e = env("empty-estate.json")
    body = e.client.get("/api/v1/metrics/latest", headers=AUTH).json()
    for f in body["families"]:
        assert f["coverage"]["eligible"] == 0 and f["coverage"]["freshReportPercent"] is None
