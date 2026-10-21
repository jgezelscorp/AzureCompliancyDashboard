"""Load the stored evidence as a bundle, compute metrics and persist history snapshots."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import AssignmentRow, CheckRow, MachineRow, ReportRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow, PolicyStateRow
from app.metrics.engine import FAMILIES, STALE_AFTER, compute, unclassified_policy_states
from app.models import EvidenceBundle


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def load_bundle(
    session: Session,
    snapshot_at: datetime,
    machines_seen_since: datetime | None = None,
    subscription_ids: frozenset[str] | None = None,
) -> EvidenceBundle:
    """Build an evidence bundle from the database.

    Only the latest report per machine and family is loaded with its checks; that is all the
    metrics need. ``machines_seen_since`` drops machines no longer present in inventory;
    ``subscription_ids`` (when given) restricts everything to those subscriptions.
    """
    machine_q = select(MachineRow)
    if machines_seen_since is not None:
        machine_q = machine_q.where(MachineRow.last_seen_at >= machines_seen_since)
    if subscription_ids is not None:
        machine_q = machine_q.where(MachineRow.subscription_id.in_(subscription_ids))
    machines = list(session.scalars(machine_q))
    ids = {m.machine_id for m in machines}

    assignments = [a for a in session.scalars(select(AssignmentRow)) if a.machine_id in ids]

    latest: dict[tuple[str, str], ReportRow] = {}
    newest = (
        select(
            ReportRow.machine_id.label("mid"),
            ReportRow.baseline_family.label("fam"),
            func.max(ReportRow.end_time).label("mx"),
        )
        .group_by(ReportRow.machine_id, ReportRow.baseline_family)
        .subquery()
    )
    report_q = select(ReportRow).join(
        newest,
        and_(
            ReportRow.machine_id == newest.c.mid,
            ReportRow.baseline_family == newest.c.fam,
            ReportRow.end_time == newest.c.mx,
        ),
    )
    for r in session.scalars(report_q.order_by(ReportRow.report_id)):
        if r.machine_id in ids:
            latest.setdefault((r.machine_id, r.baseline_family), r)
    checks_by_report: dict[str, list[CheckRow]] = {}
    if latest:
        wanted = {r.report_id for r in latest.values()}
        for c in session.scalars(select(CheckRow).where(CheckRow.report_id.in_(wanted))):
            checks_by_report.setdefault(c.report_id, []).append(c)

    return EvidenceBundle.model_validate(
        {
            "schemaVersion": "1.0.0",
            "snapshotAt": snapshot_at,
            "machines": [
                {
                    "machineId": m.machine_id,
                    "name": m.name,
                    "kind": m.kind,
                    "subscriptionId": m.subscription_id,
                    "resourceGroup": m.resource_group,
                    "location": m.location,
                    "osType": m.os_type,
                    "osName": m.os_name,
                    "osBuild": m.os_build,
                    "eligibility": m.eligibility,
                    "tags": m.tags,
                }
                for m in machines
            ],
            "assignments": [
                {
                    "assignmentId": a.assignment_id,
                    "machineId": a.machine_id,
                    "baselineFamily": a.baseline_family,
                    "guestConfigurationName": a.guest_configuration_name,
                    "complianceStatus": a.compliance_status,
                }
                for a in assignments
            ],
            "reports": [
                {
                    "reportId": r.report_id,
                    "assignmentId": r.assignment_id,
                    "machineId": r.machine_id,
                    "baselineFamily": r.baseline_family,
                    "complianceStatus": r.compliance_status,
                    "startTime": _utc(r.start_time),
                    "endTime": _utc(r.end_time),
                    "checks": [
                        {
                            "checkKey": c.check_key,
                            "name": c.name,
                            "complianceStatus": c.compliance_status,
                            "category": c.category,
                            "severity": c.severity,
                            "benchmarkControlId": c.benchmark_control_id,
                            "reasons": c.reasons or [],
                        }
                        for c in checks_by_report.get(r.report_id, [])
                    ],
                }
                for r in latest.values()
            ],
            "policyStates": [
                {
                    "resourceId": p.resource_id,
                    "policyAssignmentId": p.policy_assignment_id,
                    "policyDefinitionId": p.policy_definition_id,
                    "baselineFamily": p.baseline_family,
                    "complianceState": p.compliance_state,
                    "timestamp": _utc(p.state_timestamp),
                }
                for p in session.scalars(select(PolicyStateRow))
                if p.resource_id in ids
            ],
        }
    )


def write_snapshots(
    session: Session,
    run_id: int,
    snapshot_at: datetime,
    collection_status: str,
    bundle: EvidenceBundle,
    stale_after: timedelta = STALE_AFTER,
) -> list[int]:
    ids: list[int] = []
    unclassified = unclassified_policy_states(bundle)
    for family in FAMILIES:
        m = compute(bundle, family, snapshot_at, stale_after)
        snap = MetricSnapshotRow(
            run_id=run_id,
            snapshot_at=snapshot_at,
            family=family,
            collection_status=collection_status,
            policy_compliance=m["policyCompliance"],
            check_pass_rate=m["checkPassRate"],
            coverage=m["coverage"],
            unclassified_policy_states=unclassified,
        )
        session.add(snap)
        session.flush()
        for ms in m["machines"]:
            session.add(
                MachineStatusSnapshotRow(
                    snapshot_id=snap.id,
                    machine_id=ms["machineId"],
                    family=family,
                    evidence_quality=ms["evidenceQuality"],
                    reported_state=ms["reportedState"],
                    green=ms["green"],
                )
            )
        ids.append(snap.id)
    return ids


def snapshot_to_dict(row: MetricSnapshotRow) -> dict[str, Any]:
    return {
        "snapshotId": row.id,
        "runId": row.run_id,
        "snapshotAt": _utc(row.snapshot_at).isoformat(),
        "collectionStatus": row.collection_status,
        "family": row.family,
        "policyCompliance": row.policy_compliance,
        "checkPassRate": row.check_pass_rate,
        "coverage": row.coverage,
        "unclassifiedPolicyStates": row.unclassified_policy_states,
    }
