"""End-to-end collection against a synthetic ARM transport (no live Azure)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.azure.client import ArmClient, ArmRequest, ArmResponse
from app.collectors.normalize import parse_ts
from app.collectors.runner import CollectionRunner
from app.config import Settings
from app.db import AssignmentRow, CheckRow, CollectionRunRow, MachineRow, ReportRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow, PolicyStateRow
from app.metrics.engine import FAMILIES
from tests.azure_fakes import FakeArm
from tests.conftest import FIXTURES, load_fixture
from tests.sqlite_compat import make_session_factory

FIXTURE_NAMES = sorted(p.name for p in FIXTURES.glob("*.json"))
SUB = "00000000-0000-0000-0000-000000000000"
FAMILY_MAP = {
    "00000000-0000-0000-0000-0000000000a1": "AzureWindowsBaseline",
    "6dcfa239-b481-4de9-a03f-980f24f3b0bb": "CISWindowsSecurityBaseline",
}


class NoSleepToken:
    def get_token(self, scope: str) -> str:
        return "synthetic-token"


def snap_ts(bundle: dict[str, Any]) -> datetime:
    ts = parse_ts(bundle["snapshotAt"])
    assert ts is not None
    return ts


def make_runner(
    bundle: dict[str, Any],
    factory: sessionmaker[Session] | None = None,
    clock: datetime | None = None,
    fake: FakeArm | None = None,
    **settings: Any,
) -> tuple[CollectionRunner, FakeArm, sessionmaker[Session]]:
    factory = factory or make_session_factory()
    fake = fake or FakeArm(bundle)
    cfg = Settings(
        environment="test",
        subscription_ids=[SUB],
        policy_family_map=FAMILY_MAP,
        collection_concurrency=settings.pop("collection_concurrency", 1),
        **settings,
    )
    snapshot = clock or snap_ts(bundle)
    assert snapshot is not None
    client = ArmClient(
        fake,
        NoSleepToken(),
        allowed_subscriptions=frozenset([SUB]),
        sleep=lambda _s: None,
    )
    return CollectionRunner(cfg, factory, client, clock=lambda: snapshot), fake, factory


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_collection_reproduces_fixture_expectations(name: str) -> None:
    bundle = load_fixture(name)
    runner, fake, factory = make_runner(bundle)
    result = runner.run_once()
    assert result is not None and result.status == "succeeded", result
    with factory() as s:
        snaps = {r.family: r for r in s.scalars(select(MetricSnapshotRow))}
        for family, exp in (bundle.get("expected") or {}).items():
            if family not in FAMILIES:
                continue
            row = snaps[family]
            assert row.policy_compliance == exp["policyCompliance"]
            assert row.check_pass_rate == exp["checkPassRate"]
            assert row.coverage == exp["coverage"]
            stored = {
                m.machine_id: (m.evidence_quality, m.reported_state, m.green)
                for m in s.scalars(
                    select(MachineStatusSnapshotRow).where(
                        MachineStatusSnapshotRow.snapshot_id == row.id
                    )
                )
            }
            wanted = {
                m["machineId"]: (m["evidenceQuality"], m["reportedState"], m["green"])
                for m in exp["machines"]
            }
            assert stored == wanted
    assert {r.method for r in fake.requests} <= {"GET", "POST"}
    assert not any("triggerevaluation" in r.url.lower() for r in fake.requests)


def test_golden_373_checks_in_database() -> None:
    bundle = load_fixture("arc-azurewindowsbaseline-373.json")
    runner, _, factory = make_runner(bundle)
    runner.run_once()
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(CheckRow)) == 373
        done = s.scalar(
            select(func.count())
            .select_from(CheckRow)
            .where(CheckRow.compliance_status == "Compliant")
        )
        assert done == 109


def test_rerun_is_idempotent_and_history_grows() -> None:
    bundle = load_fixture("cis-synthetic-mixed.json")
    runner, _, factory = make_runner(bundle)
    first = runner.run_once()
    with factory() as s:
        counts = [
            s.scalar(select(func.count()).select_from(t))
            for t in (MachineRow, AssignmentRow, ReportRow, CheckRow, PolicyStateRow)
        ]
    second_runner, _, _ = make_runner(
        bundle,
        factory,
        clock=snap_ts(bundle) + timedelta(hours=6),
    )
    second = second_runner.run_once()
    assert first and second and first.run_id != second.run_id
    with factory() as s:
        again = [
            s.scalar(select(func.count()).select_from(t))
            for t in (MachineRow, AssignmentRow, ReportRow, CheckRow, PolicyStateRow)
        ]
        assert again == counts
        assert s.scalar(select(func.count()).select_from(MetricSnapshotRow)) == 4
        assert s.scalar(select(func.count()).select_from(CollectionRunRow)) == 2


def test_stale_reports_age_out_to_not_green() -> None:
    bundle = load_fixture("dual-family-distinct.json")
    runner, _, factory = make_runner(bundle)
    runner.run_once()
    later = snap_ts(bundle) + timedelta(hours=30)
    runner2, _, _ = make_runner(bundle, factory, clock=later)
    runner2.run_once()
    with factory() as s:
        latest = s.scalars(
            select(MetricSnapshotRow)
            .where(MetricSnapshotRow.family == "AzureWindowsBaseline")
            .order_by(MetricSnapshotRow.snapshot_at.desc())
        ).first()
        assert latest is not None
        assert latest.coverage["freshReport"] == 0
        assert latest.check_pass_rate["reportsExcludedAsNotFresh"] == 1
        assert latest.check_pass_rate["percent"] is None
        greens = s.scalars(
            select(MachineStatusSnapshotRow.green).where(
                MachineStatusSnapshotRow.snapshot_id == latest.id
            )
        ).all()
        assert not any(greens)


def test_no_subscriptions_fails_run_without_calls() -> None:
    bundle = load_fixture("empty-estate.json")
    factory = make_session_factory()
    fake = FakeArm(bundle)
    cfg = Settings(environment="test")
    client = ArmClient(fake, NoSleepToken(), sleep=lambda _s: None)
    result = CollectionRunner(cfg, factory, client).run_once()
    assert result is not None and result.status == "failed"
    assert fake.requests == []


def test_partial_when_machine_access_denied() -> None:
    bundle = load_fixture("cis-synthetic-mixed.json")
    denied = bundle["assignments"][0]["machineId"]

    def deny(req: ArmRequest) -> ArmResponse | None:
        if denied in req.url.lower() and "guestconfigurationassignments" in req.url.lower():
            return ArmResponse(403, {}, {"error": {"code": "AuthorizationFailed", "message": "x"}})
        return None

    runner, _, factory = make_runner(bundle, fake=FakeArm(bundle, overrides=deny))
    result = runner.run_once()
    assert result is not None and result.status == "partial"
    assert any(e["kind"] == "AccessDenied" for e in result.errors)
    with factory() as s:
        run = s.get(CollectionRunRow, result.run_id)
        assert run is not None and run.status == "partial"
        assert run.checkpoint is not None and run.checkpoint.get("errorCount", 0) != 0


def test_arg_failure_fails_run_and_writes_no_snapshot() -> None:
    bundle = load_fixture("cis-synthetic-mixed.json")

    def boom(req: ArmRequest) -> ArmResponse | None:
        if "resourcegraph" in req.url.lower():
            return ArmResponse(500, {}, {})
        return None

    runner, _, factory = make_runner(bundle, fake=FakeArm(bundle, overrides=boom))
    result = runner.run_once()
    assert result is not None and result.status == "failed"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(MetricSnapshotRow)) == 0


def test_arg_truncation_marks_run_partial() -> None:
    bundle = load_fixture("cis-synthetic-mixed.json")

    def truncated(req: ArmRequest) -> ArmResponse | None:
        if "resourcegraph" in req.url.lower():
            return ArmResponse(200, {}, {"data": [], "resultTruncated": "true"})
        return None

    runner, _, _ = make_runner(bundle, fake=FakeArm(bundle, overrides=truncated))
    result = runner.run_once()
    assert result is not None and result.status == "partial"
    assert any(e["kind"] == "Truncated" for e in result.errors)


def test_overlapping_run_is_skipped_and_stale_run_abandoned() -> None:
    bundle = load_fixture("empty-estate.json")
    runner, fake, factory = make_runner(bundle)
    now = snap_ts(bundle)
    assert now is not None
    with factory() as s, s.begin():
        s.add(CollectionRunRow(started_at=now - timedelta(minutes=5), status="running"))
    assert runner.run_once() is None
    assert fake.requests == []
    with factory() as s, s.begin():
        row = s.scalars(select(CollectionRunRow)).one()
        row.started_at = now - timedelta(hours=5)
    result = runner.run_once()
    assert result is not None
    with factory() as s:
        statuses = sorted(r.status for r in s.scalars(select(CollectionRunRow)))
        assert "abandoned" in statuses


def test_bounded_concurrency_gives_same_result() -> None:
    bundle = load_fixture("cis-synthetic-mixed.json")
    a, _, fa = make_runner(bundle, collection_concurrency=1)
    b, _, fb = make_runner(bundle, collection_concurrency=4)
    a.run_once()
    b.run_once()
    with fa() as sa, fb() as sb:
        pa = [
            r.coverage
            for r in sa.scalars(select(MetricSnapshotRow).order_by(MetricSnapshotRow.family))
        ]
        pb = [
            r.coverage
            for r in sb.scalars(select(MetricSnapshotRow).order_by(MetricSnapshotRow.family))
        ]
        assert pa == pb


def test_thirteen_month_retention_purges_old_history() -> None:
    bundle = load_fixture("dual-family-distinct.json")
    runner, _, factory = make_runner(bundle)
    runner.run_once()
    far = snap_ts(bundle) + timedelta(days=430)
    runner2, _, _ = make_runner(bundle, factory, clock=far)
    result = runner2.run_once()
    assert result is not None
    with factory() as s:
        snaps = s.scalars(select(MetricSnapshotRow.snapshot_at)).all()
        assert all(
            (t if t.tzinfo else t.replace(tzinfo=UTC)) >= far - timedelta(days=400) for t in snaps
        )
        assert s.scalar(select(func.count()).select_from(MetricSnapshotRow)) == 2
        # the old report is outside the window and gone; the late-arriving copy is not re-added
        assert s.scalar(select(func.count()).select_from(ReportRow)) == 0
