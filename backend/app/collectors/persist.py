"""Idempotent persistence of normalized evidence (re-running a collection never duplicates)."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, exists, or_, select, update
from sqlalchemy.orm import Session

from app.db import AssignmentRow, CheckRow, CollectionRunRow, MachineRow, ReportRow
from app.db_history import (
    MachineStatusSnapshotRow,
    MetricSnapshotRow,
    PolicyStateRow,
)
from app.db_policy import (
    DefenderSnapshotRow,
    EstateResourceRow,
    EstateSnapshotRow,
    PolicyAssignmentRow,
    PolicyExemptionRow,
)
from app.domain.categories import (
    configured_overrides,
    derive_category,
    resolve_category,
    rules_version,
)
from app.metrics.policy import diff_states
from app.models import Assignment, Machine, PolicyState, Report


def upsert_machines(session: Session, machines: Iterable[Machine], seen_at: datetime) -> None:
    for m in machines:
        row = session.get(MachineRow, m.machine_id)
        if row is None:
            row = MachineRow(machine_id=m.machine_id, first_seen_at=seen_at)
            session.add(row)
        row.name = m.name
        row.kind = m.kind
        row.subscription_id = m.subscription_id
        row.resource_group = m.resource_group
        row.location = m.location
        row.os_type = m.os_type
        row.os_name = m.os_name
        row.os_build = m.os_build
        row.eligibility = m.eligibility
        row.tags = m.tags
        row.last_seen_at = seen_at


def touch_subscriptions(session: Session, subscription_ids: set[str], seen_at: datetime) -> None:
    """Keep machines of subscriptions whose inventory is uncertain from silently dropping out."""
    if subscription_ids:
        session.execute(
            update(MachineRow)
            .where(MachineRow.subscription_id.in_(subscription_ids))
            .values(last_seen_at=seen_at)
        )


def upsert_assignments(session: Session, assignments: Iterable[Assignment], run_id: int) -> None:
    for a in assignments:
        row = session.get(AssignmentRow, a.assignment_id)
        if row is None:
            row = AssignmentRow(assignment_id=a.assignment_id)
            session.add(row)
        row.machine_id = a.machine_id
        row.baseline_family = a.baseline_family
        row.guest_configuration_name = a.guest_configuration_name
        row.guest_configuration_version = a.guest_configuration_version
        row.policy_definition_id = a.policy_definition_id
        row.policy_definition_version = a.policy_definition_version
        row.policy_assignment_id = a.policy_assignment_id
        row.assignment_hash = a.assignment_hash
        row.parameter_hash = a.parameter_hash
        row.content_hash = a.content_hash
        row.include_arc_machines = a.include_arc_machines
        row.compliance_status = a.compliance_status
        row.last_compliance_status_checked = a.last_compliance_status_checked
        row.run_id = run_id


def _add_checks(session: Session, report: Report) -> None:
    for c in report.checks:
        resolved = resolve_category(c.name, c.check_key, c.category, configured_overrides())
        session.add(
            CheckRow(
                report_id=report.report_id,
                check_key=c.check_key,
                name=c.name,
                compliance_status=c.compliance_status,
                category=c.category,
                derived_category=derive_category(c.name),
                category_source=resolved.source,
                category_rule_version=resolved.rule_version,
                severity=c.severity,
                benchmark_control_id=c.benchmark_control_id,
                reasons=[x.model_dump() for x in c.reasons],
            )
        )


def recategorize_checks(session: Session) -> int:
    """Recompute derived category columns for rows stamped with an older rule version.

    Only app-derived columns change; the raw source category and the evidence are untouched.
    Overrides and the rule file are applied at read time as well, so reads are always current.
    """
    version = rules_version()
    overrides = configured_overrides()
    rows = session.scalars(
        select(CheckRow).where(
            or_(
                CheckRow.category_rule_version.is_(None),
                CheckRow.category_rule_version != version,
            )
        )
    ).all()
    for row in rows:
        resolved = resolve_category(row.name, row.check_key, row.category, overrides)
        row.derived_category = derive_category(row.name)
        row.category_source = resolved.source
        row.category_rule_version = resolved.rule_version
    return len(rows)


def insert_reports(session: Session, reports: Iterable[Report], run_id: int) -> int:
    """Reports are immutable upstream: an existing report id is skipped.

    An existing report that has no stored checks (e.g. written by an older parser) gets its
    checks filled in; it is not counted as inserted.
    """
    inserted = 0
    for r in reports:
        if session.get(ReportRow, r.report_id) is not None:
            has_checks = session.scalar(select(exists().where(CheckRow.report_id == r.report_id)))
            if not has_checks and r.checks:
                _add_checks(session, r)
            continue
        session.add(
            ReportRow(
                report_id=r.report_id,
                assignment_id=r.assignment_id,
                machine_id=r.machine_id,
                baseline_family=r.baseline_family,
                compliance_status=r.compliance_status,
                start_time=r.start_time,
                end_time=r.end_time,
                operation_type=r.operation_type,
                configuration_version=r.configuration_version,
                run_id=run_id,
            )
        )
        session.flush()
        _add_checks(session, r)
        inserted += 1
    return inserted


def replace_policy_states(
    session: Session,
    subscription_id: str,
    states: Iterable[PolicyState],
    run_id: int,
    extras: dict[tuple[str, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Upsert the latest states for a subscription; rows not returned this run are removed.

    Returns the change set against the previous collection (regressions, recoveries, ...).
    """
    old = {
        (r.resource_id, r.policy_assignment_id, r.reference_id): r.compliance_state
        for r in session.execute(
            select(
                PolicyStateRow.resource_id,
                PolicyStateRow.policy_assignment_id,
                PolicyStateRow.reference_id,
                PolicyStateRow.compliance_state,
            ).where(PolicyStateRow.subscription_id == subscription_id)
        )
    }
    new: dict[tuple[str, str, str], str] = {}
    for s in states:
        key = (s.resource_id, s.policy_assignment_id, s.policy_definition_reference_id or "")
        row = session.get(PolicyStateRow, key)
        if row is None:
            row = PolicyStateRow(
                resource_id=key[0], policy_assignment_id=key[1], reference_id=key[2]
            )
            session.add(row)
        row.subscription_id = subscription_id
        row.policy_definition_id = s.policy_definition_id
        row.baseline_family = s.baseline_family or "Unknown"
        row.compliance_state = s.compliance_state
        row.is_compliant = s.is_compliant
        row.state_timestamp = s.timestamp
        row.run_id = run_id
        for name, value in (extras or {}).get(key, {}).items():
            setattr(row, name, value)
        new[key] = s.compliance_state
    session.flush()
    session.execute(
        delete(PolicyStateRow).where(
            PolicyStateRow.subscription_id == subscription_id,
            or_(PolicyStateRow.run_id != run_id, PolicyStateRow.run_id.is_(None)),
        )
    )
    return diff_states(old, new)


def add_months(value: datetime, months: int) -> datetime:
    """Calendar-month arithmetic; the day is clamped to the target month length."""
    index = value.year * 12 + (value.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    for day in (value.day, 30, 29, 28):
        try:
            return value.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise AssertionError("unreachable")  # pragma: no cover


def retention_cutoff(now: datetime, months: int) -> datetime:
    return add_months(now, -months)


def _count(result: object) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


def purge_history(session: Session, now: datetime, months: int = 13) -> dict[str, int]:
    """Delete evidence and metric history older than the retention window (13 calendar months)."""
    cutoff = retention_cutoff(now, months)
    old_snapshots = select(MetricSnapshotRow.id).where(MetricSnapshotRow.snapshot_at < cutoff)
    old_reports = select(ReportRow.report_id).where(ReportRow.end_time < cutoff)
    out: dict[str, int] = {}
    session.execute(
        delete(MachineStatusSnapshotRow).where(
            MachineStatusSnapshotRow.snapshot_id.in_(old_snapshots)
        )
    )
    out["snapshots"] = _count(
        session.execute(delete(MetricSnapshotRow).where(MetricSnapshotRow.snapshot_at < cutoff))
    )
    session.execute(delete(CheckRow).where(CheckRow.report_id.in_(old_reports)))
    out["reports"] = _count(session.execute(delete(ReportRow).where(ReportRow.end_time < cutoff)))
    out["estateSnapshots"] = _count(
        session.execute(delete(EstateSnapshotRow).where(EstateSnapshotRow.snapshot_at < cutoff))
    )
    session.execute(delete(DefenderSnapshotRow).where(DefenderSnapshotRow.snapshot_at < cutoff))
    referenced = or_(
        exists().where(ReportRow.run_id == CollectionRunRow.run_id),
        exists().where(AssignmentRow.run_id == CollectionRunRow.run_id),
        exists().where(PolicyStateRow.run_id == CollectionRunRow.run_id),
        exists().where(MetricSnapshotRow.run_id == CollectionRunRow.run_id),
        exists().where(EstateSnapshotRow.run_id == CollectionRunRow.run_id),
        exists().where(DefenderSnapshotRow.run_id == CollectionRunRow.run_id),
        exists().where(PolicyAssignmentRow.run_id == CollectionRunRow.run_id),
        exists().where(PolicyExemptionRow.run_id == CollectionRunRow.run_id),
        exists().where(EstateResourceRow.run_id == CollectionRunRow.run_id),
    )
    out["runs"] = _count(
        session.execute(
            delete(CollectionRunRow).where(CollectionRunRow.started_at < cutoff, ~referenced)
        )
    )
    return out


__all__ = [
    "add_months",
    "insert_reports",
    "purge_history",
    "replace_policy_states",
    "retention_cutoff",
    "touch_subscriptions",
    "upsert_assignments",
    "upsert_machines",
]
