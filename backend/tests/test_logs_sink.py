"""Optional Log Analytics sink: schema, row mapping, delivery, outage handling. No network."""

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.azure.client import ArmClient, ArmRequest, ArmResponse, TransportError
from app.collectors.runner import CollectionRunner
from app.config import Settings
from app.db import CollectionRunRow
from app.db_sink import STATUS_DEAD, STATUS_DELIVERED, STATUS_PENDING, LogsOutboxRow
from app.sink import schema
from app.sink.outbox import delivery_summary
from app.sink.service import LogsSink, build_sink
from tests.azure_fakes import FakeArm
from tests.conftest import load_fixture
from tests.sqlite_compat import make_session_factory
from tests.test_collector_run import FAMILY_MAP, SUB, NoSleepToken, snap_ts
from tests.test_metrics_api import AUTH, Env

ENDPOINT = "https://example-dce.westeurope-1.ingest.monitor.azure.com"
DCR = "dcr-" + "0" * 32
ROOT = Path(__file__).resolve().parents[2]

Responder = Callable[[ArmRequest], ArmResponse | Exception]


class FakeLogs:
    """Transport double for the Logs Ingestion API; stores accepted rows per stream."""

    def __init__(self, responder: Responder | None = None) -> None:
        self.responder = responder
        self.requests: list[ArmRequest] = []
        self.accepted: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def send(self, request: ArmRequest) -> ArmResponse:
        self.requests.append(request)
        if self.responder is not None:
            out = self.responder(request)
            if isinstance(out, Exception):
                raise out
            if out.status >= 300:
                return out
        stream = request.url.split("/streams/")[1].split("?")[0]
        self.accepted[stream].extend(request.json)
        return ArmResponse(204, {}, None)


class Tokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> str:
        self.scopes.append(scope)
        if self.fail:
            raise RuntimeError("credential details that must never be stored")
        return "synthetic-token"


def logs_settings(**kw: Any) -> Settings:
    return Settings(
        environment="test",
        subscription_ids=[SUB],
        policy_family_map=FAMILY_MAP,
        collection_concurrency=1,
        logs_sink_enabled=True,
        logs_ingestion_endpoint=ENDPOINT,
        logs_dcr_immutable_id=DCR,
        **kw,
    )


class Rig:
    def __init__(
        self,
        fixture: str = "arc-azurewindowsbaseline-373.json",
        responder: Responder | None = None,
        tokens: Tokens | None = None,
        **kw: Any,
    ) -> None:
        self.bundle = load_fixture(fixture)
        self.factory: sessionmaker[Session] = make_session_factory()
        self.now = snap_ts(self.bundle)
        self.logs = FakeLogs(responder)
        self.sleeps: list[float] = []
        self.cfg = logs_settings(**kw)
        built = build_sink(self.cfg, self.factory, self.logs, tokens or Tokens())
        assert built is not None
        self.sink: LogsSink = LogsSink(
            self.cfg,
            self.factory,
            built._delivery._client,
            clock=lambda: self.now,
            sleep=self.sleeps.append,
        )
        arm = ArmClient(
            FakeArm(self.bundle), NoSleepToken(), allowed_subscriptions=frozenset([SUB]),
            sleep=lambda _s: None,
        )
        self.runner = CollectionRunner(
            self.cfg, self.factory, arm, clock=lambda: self.now, sink=self.sink
        )

    def outbox(self) -> dict[str, int]:
        with self.factory() as s:
            rows = s.execute(
                select(LogsOutboxRow.status, func.count()).group_by(LogsOutboxRow.status)
            ).all()
            return {str(status): int(n) for status, n in rows}


def stream_of(table: str) -> str:
    return schema.tables()[table].stream


def fresh_check_totals(accepted: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    """The same logic as workbooks/queries/_fragments/logs_fresh.kql, over delivered rows."""
    runs = accepted[stream_of(schema.RUNS)]
    latest = max(datetime.fromisoformat(r["TimeGenerated"]) for r in runs)
    end: dict[tuple[str, str], str] = {}
    for r in accepted[stream_of(schema.REPORTS)]:
        k = (r["MachineId"], r["Family"])
        end[k] = max(end.get(k, r["ReportEndTime"]), r["ReportEndTime"])
    pick: dict[tuple[str, str], int] = {}
    for r in accepted[stream_of(schema.REPORTS)]:
        k = (r["MachineId"], r["Family"])
        if r["ReportEndTime"] == end[k]:
            pick[k] = min(pick.get(k, r["ReportId"]), r["ReportId"])
    fresh = {
        rid
        for k, rid in pick.items()
        if datetime.fromisoformat(end[k]) >= latest - timedelta(hours=24)
    }
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for c in accepted[stream_of(schema.CHECKS)]:
        seen.setdefault((c["ReportId"], c["CheckKey"]), c)
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0, "total": 0})
    for (rid, _), c in seen.items():
        if rid not in fresh:
            continue
        bucket = out[c["Family"]]
        bucket["total"] += 1
        bucket["passed" if c["ComplianceStatus"] == "Compliant" else "failed"] += 1
    return dict(out)


def test_packaged_schema_matches_contract_and_is_versioned() -> None:
    contract = (ROOT / "contracts" / "logs-schema.json").read_bytes()
    packaged = (Path(schema.__file__).parent / "logs-schema.json").read_bytes()
    assert contract == packaged
    assert set(schema.tables()) == {
        "ComplianceCollectionRuns_CL",
        "PolicyComplianceSnapshots_CL",
        "MachineConfigReports_CL",
        "MachineConfigChecks_CL",
    }
    doc = json.loads(contract)
    assert doc["retention"]["minimumInteractiveDays"] >= 397  # 13 months
    for table in doc["tables"]:
        names = [c["name"] for c in table["columns"]]
        assert {"TimeGenerated", "RecordKey", "SchemaVersion", "SentAt", "RunId"} <= set(names)
        assert len(names) == len(set(names))


def test_delivery_reproduces_fixture_check_totals_per_family() -> None:
    rig = Rig()
    result = rig.runner.run_once()
    assert result is not None and result.status == "succeeded"
    assert rig.outbox() == {STATUS_DELIVERED: sum(len(v) for v in rig.logs.accepted.values())}
    for stream, rows in rig.logs.accepted.items():
        table = stream.removeprefix("Custom-")
        for row in rows:
            schema.validate_row(table, row, sent=True)
            assert row["SentAt"]
    expected = rig.bundle["expected"]
    totals = fresh_check_totals(rig.logs.accepted)
    for family, exp in expected.items():
        want = exp["checkPassRate"]
        got = totals.get(family, {"passed": 0, "failed": 0, "total": 0})
        assert (got["passed"], got["failed"], got["total"]) == (
            want["passed"],
            want["failed"],
            want["total"],
        )
    assert totals["AzureWindowsBaseline"]["total"] == 373


def test_rows_carry_no_secrets_or_error_text_and_requests_use_scope_and_url() -> None:
    tokens = Tokens()
    rig = Rig(tokens=tokens)
    rig.runner.run_once()
    assert set(tokens.scopes) == {"https://monitor.azure.com//.default"}
    first = rig.logs.requests[0]
    assert first.url.startswith(f"{ENDPOINT}/dataCollectionRules/{DCR}/streams/Custom-")
    assert first.url.endswith("?api-version=2023-01-01")
    blob = json.dumps(rig.logs.accepted)
    assert "synthetic-token" not in blob and "Bearer" not in blob


def test_outage_never_invalidates_collection_and_recovery_has_no_duplicates() -> None:
    down = {"on": True}

    def responder(_: ArmRequest) -> ArmResponse | Exception:
        return ArmResponse(503, {}, {"error": {"code": "ServiceUnavailable"}}) if down["on"] else (
            ArmResponse(204, {}, None)
        )

    rig = Rig(responder=responder)
    result = rig.runner.run_once()
    assert result is not None and result.status == "succeeded"
    with rig.factory() as s:
        run = s.scalars(select(CollectionRunRow)).one()
        assert run.status == "succeeded"
        summary = delivery_summary(s, rig.now)
    assert summary["state"] in ("backlog", "degraded") and summary["pending"] > 0
    assert rig.outbox().get(STATUS_DELIVERED, 0) == 0
    assert len(rig.sleeps) >= 1  # inline retry used backoff

    down["on"] = False
    rig.now += timedelta(hours=7)  # past the reschedule backoff
    assert rig.sink.drain() is not None
    assert STATUS_PENDING not in rig.outbox() and STATUS_DEAD not in rig.outbox()
    keys = [(s, r["RecordKey"]) for s, rows in rig.logs.accepted.items() for r in rows]
    assert len(keys) == len(set(keys))


def test_throttling_honours_retry_after() -> None:
    state = {"n": 0}

    def responder(_: ArmRequest) -> ArmResponse | Exception:
        state["n"] += 1
        if state["n"] == 1:
            return ArmResponse(429, {"Retry-After": "2"}, None)
        return ArmResponse(204, {}, None)

    rig = Rig(responder=responder)
    rig.runner.run_once()
    assert 2.0 in rig.sleeps
    assert STATUS_PENDING not in rig.outbox()


def test_rejected_row_is_isolated_and_good_rows_are_delivered() -> None:
    bad_key: dict[str, str] = {}

    def responder(req: ArmRequest) -> ArmResponse | Exception:
        if "ComplianceCollectionRuns_CL" in req.url:
            return ArmResponse(204, {}, None)
        if "MachineConfigChecks_CL" in req.url:
            if not bad_key:
                bad_key["k"] = req.json[0]["RecordKey"]
            if any(r["RecordKey"] == bad_key["k"] for r in req.json):
                return ArmResponse(400, {}, {"error": {"code": "InvalidData"}})
        return ArmResponse(204, {}, None)

    rig = Rig(responder=responder)
    rig.runner.run_once()
    status = rig.outbox()
    assert status[STATUS_DEAD] == 1
    assert STATUS_PENDING not in status
    delivered_checks = rig.logs.accepted["Custom-MachineConfigChecks_CL"]
    assert bad_key["k"] not in {r["RecordKey"] for r in delivered_checks}
    assert len(delivered_checks) > 300


def test_token_failure_is_transient_and_leaks_nothing() -> None:
    rig = Rig(tokens=Tokens(fail=True))
    result = rig.runner.run_once()
    assert result is not None and result.status == "succeeded"
    with rig.factory() as s:
        errors = {e for e in s.scalars(select(LogsOutboxRow.last_error)) if e}
        summary = delivery_summary(s, rig.now)
    assert errors and all("credential" not in e for e in errors)
    assert "credential" not in json.dumps(summary)
    assert summary["pending"] > 0 and not rig.logs.requests


def test_transport_error_is_transient() -> None:
    rig = Rig(responder=lambda _r: TransportError("boom"))
    result = rig.runner.run_once()
    assert result is not None and result.status == "succeeded"
    assert rig.outbox().get(STATUS_PENDING, 0) > 0


def test_rows_go_dead_after_max_attempts_but_collection_stays_valid() -> None:
    rig = Rig(responder=lambda _r: ArmResponse(500, {}, None), logs_max_attempts=2)
    rig.runner.run_once()
    for _ in range(3):
        rig.now += timedelta(days=1)
        rig.sink.drain()
    assert rig.outbox().get(STATUS_DEAD, 0) > 0
    with rig.factory() as s:
        assert s.scalars(select(CollectionRunRow.status)).one() == "succeeded"
        assert delivery_summary(s, rig.now)["state"] == "degraded"


def test_enqueue_is_idempotent_per_record_key() -> None:
    rig = Rig(responder=lambda _r: ArmResponse(503, {}, None))
    rig.runner.run_once()
    before = sum(rig.outbox().values())
    with rig.factory() as s:
        run_id = s.scalars(select(CollectionRunRow.run_id)).one()
    rig.sink.publish(run_id)
    assert sum(rig.outbox().values()) == before


def test_sink_exception_is_contained_in_the_runner() -> None:
    rig = Rig()

    class Boom:
        def publish(self, run_id: int) -> None:
            raise RuntimeError("sink bug")

    rig.runner._sink = Boom()  # type: ignore[assignment]
    try:
        result = rig.runner.run_once()
    except RuntimeError:  # pragma: no cover
        pytest.fail("sink failure must not escape run_once")
    assert result is not None and result.status == "succeeded"


def test_sink_is_off_by_default_and_runner_works_without_it() -> None:
    assert build_sink(Settings(environment="test"), make_session_factory()) is None
    assert Settings(environment="test").logs_sink_enabled is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://x.ingest.monitor.azure.com",
        "https://evil.example.com",
        "https://x.ingest.monitor.azure.com.evil.example",
        "https://user@x.ingest.monitor.azure.com",
        "https://x.ingest.monitor.azure.com/path",
        "",
    ],
)
def test_endpoint_must_be_an_azure_ingestion_origin(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            logs_sink_enabled=True,
            logs_ingestion_endpoint=endpoint,
            logs_dcr_immutable_id=DCR,
        )


def test_dcr_id_must_be_well_formed() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            logs_sink_enabled=True,
            logs_ingestion_endpoint=ENDPOINT,
            logs_dcr_immutable_id="not-a-dcr",
        )


def test_sink_status_api_disabled_by_default_and_counts_only_when_enabled() -> None:
    e = Env("arc-azurewindowsbaseline-373.json")
    e.register(SUB)
    assert e.client.get("/api/v1/collection/sink", headers=AUTH).json() == {"enabled": False}

    on = Env(
        "arc-azurewindowsbaseline-373.json",
        logs_sink_enabled=True,
        logs_ingestion_endpoint=ENDPOINT,
        logs_dcr_immutable_id=DCR,
    )
    on.register(SUB)
    with on.factory() as s, s.begin():
        s.add(
            LogsOutboxRow(
                stream="Custom-ComplianceCollectionRuns_CL",
                record_key="k",
                payload={"secret": "payload must not be exposed"},
                status=STATUS_PENDING,
                attempts=1,
                created_at=datetime.now(UTC) - timedelta(hours=1),
                next_attempt_at=datetime.now(UTC),
                last_error="TransientSinkError:503",
            )
        )
    body = on.client.get("/api/v1/collection/sink", headers=AUTH).json()
    assert body["enabled"] is True and body["pending"] == 1
    assert "payload" not in json.dumps(body) and "secret" not in json.dumps(body)
