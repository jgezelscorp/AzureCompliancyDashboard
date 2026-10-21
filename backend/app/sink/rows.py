"""Map stored collection results to Logs rows. Reads PostgreSQL only; never calls Azure."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import CheckRow, CollectionRunRow, MachineRow, ReportRow
from app.db_history import MetricSnapshotRow
from app.sink import schema

MAX_REASONS = 20
MAX_TEXT = 2000


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _text(value: str | None, limit: int = MAX_TEXT) -> str | None:
    return None if value is None else value[:limit]


def record_key(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]


def _base(table: str, run_id: int, at: datetime, key: str) -> dict[str, Any]:
    return {
        "TimeGenerated": _iso(at),
        "RecordKey": key,
        "SchemaVersion": schema.schema_version(),
        "RunId": run_id,
    }


def run_row(run: CollectionRunRow) -> dict[str, Any]:
    checkpoint = run.checkpoint or {}
    raw_counts = checkpoint.get("counts")
    counts: dict[str, Any] = raw_counts if isinstance(raw_counts, dict) else {}
    error_count = checkpoint.get("errorCount", 0)
    return {
        **_base(schema.RUNS, run.run_id, run.started_at, record_key(schema.RUNS, run.run_id)),
        "StartedAt": _iso(run.started_at),
        "FinishedAt": _iso(run.finished_at),
        "CollectionStatus": run.status,
        "SubscriptionCount": len([s for s in (run.scope or "").split(",") if s]),
        "MachineCount": int(counts.get("machines", 0)),
        "AssignmentCount": int(counts.get("assignments", 0)),
        "ReportsInserted": int(counts.get("reportsInserted", 0)),
        "PolicyStateCount": int(counts.get("policyStates", 0)),
        "ErrorCount": int(error_count) if isinstance(error_count, int) else 0,
    }


def snapshot_row(snap: MetricSnapshotRow) -> dict[str, Any]:
    pc, cp, cov = snap.policy_compliance, snap.check_pass_rate, snap.coverage
    key = record_key(schema.SNAPSHOTS, snap.run_id, snap.family)
    return {
        **_base(schema.SNAPSHOTS, snap.run_id, snap.snapshot_at, key),
        "Family": snap.family,
        "CollectionStatus": snap.collection_status,
        "PolicyCompliant": pc["compliant"],
        "PolicyNonCompliant": pc["nonCompliant"],
        "PolicyExempt": pc["exempt"],
        "PolicyOther": pc["other"],
        "PolicyCompliancePercent": pc["percent"],
        "ChecksPassed": cp["passed"],
        "ChecksFailed": cp["failed"],
        "ChecksTotal": cp["total"],
        "CheckPassPercent": cp["percent"],
        "ReportsExcludedAsNotFresh": cp["reportsExcludedAsNotFresh"],
        "EligibleMachines": cov["eligible"],
        "UnknownEligibility": cov["unknownEligibility"],
        "AssignedMachines": cov["assigned"],
        "UsableReportMachines": cov["usableReport"],
        "FreshReportMachines": cov["freshReport"],
        "AssignmentPercent": cov["assignmentPercent"],
        "UsableReportPercent": cov["usableReportPercent"],
        "FreshReportPercent": cov["freshReportPercent"],
        "UnclassifiedPolicyStates": snap.unclassified_policy_states,
    }


def _reasons(raw: list[dict[str, str | None]] | None) -> list[dict[str, str | None]]:
    return [
        {"phrase": _text(r.get("phrase"), 500), "code": _text(r.get("code"), 200)}
        for r in (raw or [])[:MAX_REASONS]
    ]


def report_and_check_rows(
    session: Session, run: CollectionRunRow
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (table, row) for every report stored by the run, with its checks."""
    reports = session.execute(
        select(ReportRow, MachineRow)
        .join(MachineRow, MachineRow.machine_id == ReportRow.machine_id)
        .where(ReportRow.run_id == run.run_id)
        .order_by(ReportRow.report_id)
    )
    for report, machine in reports:
        checks = list(
            session.scalars(
                select(CheckRow).where(CheckRow.report_id == report.report_id).order_by(CheckRow.id)
            )
        )
        failed = sum(c.compliance_status == "NonCompliant" for c in checks)
        yield (
            schema.REPORTS,
            {
                **_base(
                    schema.REPORTS,
                    run.run_id,
                    run.started_at,
                    record_key(schema.REPORTS, report.report_id),
                ),
                "ReportId": report.report_id,
                "AssignmentId": report.assignment_id,
                "MachineId": report.machine_id,
                "MachineName": _text(machine.name),
                "MachineKind": machine.kind,
                "SubscriptionId": machine.subscription_id,
                "ResourceGroup": _text(machine.resource_group),
                "Family": report.baseline_family,
                "ComplianceStatus": report.compliance_status,
                "ReportStartTime": _iso(report.start_time),
                "ReportEndTime": _iso(report.end_time),
                "OperationType": _text(report.operation_type),
                "ConfigurationVersion": _text(report.configuration_version),
                "CheckCount": len(checks),
                "FailedCheckCount": failed,
            },
        )
        for c in checks:
            yield (
                schema.CHECKS,
                {
                    **_base(
                        schema.CHECKS,
                        run.run_id,
                        run.started_at,
                        record_key(schema.CHECKS, report.report_id, c.check_key),
                    ),
                    "ReportId": report.report_id,
                    "MachineId": report.machine_id,
                    "SubscriptionId": machine.subscription_id,
                    "Family": report.baseline_family,
                    "CheckKey": _text(c.check_key),
                    "CheckName": _text(c.name),
                    "ComplianceStatus": c.compliance_status,
                    "Category": _text(c.category),
                    "Severity": c.severity,
                    "BenchmarkControlId": _text(c.benchmark_control_id),
                    "ReportEndTime": _iso(report.end_time),
                    "Reasons": _reasons(c.reasons),
                },
            )


def rows_for_run(session: Session, run: CollectionRunRow) -> Iterator[tuple[str, dict[str, Any]]]:
    yield schema.RUNS, run_row(run)
    for snap in session.scalars(
        select(MetricSnapshotRow)
        .where(MetricSnapshotRow.run_id == run.run_id)
        .order_by(MetricSnapshotRow.family)
    ):
        yield schema.SNAPSHOTS, snapshot_row(snap)
    yield from report_and_check_rows(session, run)
