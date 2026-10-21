"""Read-only metrics, history and collection-status endpoints (no write operations)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.azure.allowlist import RULES
from app.config import Settings, get_settings
from app.database import get_session
from app.db import CollectionRunRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow
from app.metrics.engine import FAMILIES
from app.metrics.store import snapshot_to_dict

router = APIRouter(prefix="/api/v1", tags=["metrics"])

Family = Literal["AzureWindowsBaseline", "CISWindowsSecurityBaseline"]
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

LABELS = [
    "Azure Policy compliance %, check pass rate and coverage are separate metrics and are "
    "never combined.",
    "Results describe Azure Policy / Machine Configuration reports; they are not a CIS, ISO, "
    "NIS2 or DORA certification or attestation.",
    "No data is not compliance: missing or stale evidence is never green.",
]
FAMILY_NOTES = {
    "AzureWindowsBaseline": "Azure Windows baseline evidence; does not count as CIS evidence.",
    "CISWindowsSecurityBaseline": (
        "Native CIS Windows family; applicability is unverified (gate G-APP) and results come "
        "only from the Machine Configuration reports of this family."
    ),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@router.get("/metrics/latest")
def latest_metrics(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    newest = session.scalar(select(func.max(MetricSnapshotRow.snapshot_at)))
    if newest is None:
        return {"snapshotAt": None, "dataStale": True, "families": [], "labels": LABELS}
    rows = session.scalars(
        select(MetricSnapshotRow).where(MetricSnapshotRow.snapshot_at == newest)
    ).all()
    age = _now() - _utc(newest)
    return {
        "snapshotAt": _utc(newest).isoformat(),
        "dataStale": age > timedelta(hours=settings.freshness_hours),
        "freshnessHours": settings.freshness_hours,
        "families": [
            {**snapshot_to_dict(r), "note": FAMILY_NOTES.get(r.family)}
            for r in sorted(rows, key=lambda r: FAMILIES.index(r.family))
        ],
        "labels": LABELS,
    }


@router.get("/metrics/history")
def metrics_history(
    session: SessionDep,
    family: Family | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    q = select(MetricSnapshotRow)
    if family:
        q = q.where(MetricSnapshotRow.family == family)
    if since:
        q = q.where(MetricSnapshotRow.snapshot_at >= _utc(since))
    if until:
        q = q.where(MetricSnapshotRow.snapshot_at <= _utc(until))
    rows = session.scalars(q.order_by(MetricSnapshotRow.snapshot_at.desc()).limit(limit)).all()
    return {
        "points": [snapshot_to_dict(r) for r in reversed(rows)],
        "samplingNote": "Samples at collection times; not continuous assessment.",
        "labels": LABELS,
    }


@router.get("/metrics/machines")
def machine_statuses(
    session: SessionDep,
    family: Family,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    snap = session.scalars(
        select(MetricSnapshotRow)
        .where(MetricSnapshotRow.family == family)
        .order_by(MetricSnapshotRow.snapshot_at.desc())
        .limit(1)
    ).first()
    if snap is None:
        return {"snapshotAt": None, "machines": [], "total": 0}
    base = select(MachineStatusSnapshotRow).where(MachineStatusSnapshotRow.snapshot_id == snap.id)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(MachineStatusSnapshotRow.machine_id).limit(limit).offset(offset)
    ).all()
    return {
        "snapshotAt": _utc(snap.snapshot_at).isoformat(),
        "family": family,
        "total": total,
        "machines": [
            {
                "machineId": r.machine_id,
                "evidenceQuality": r.evidence_quality,
                "reportedState": r.reported_state,
                "green": r.green,
            }
            for r in rows
        ],
    }


@router.get("/collection/runs")
def collection_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> dict[str, Any]:
    rows = session.scalars(
        select(CollectionRunRow).order_by(CollectionRunRow.started_at.desc()).limit(limit)
    ).all()
    return {
        "runs": [
            {
                "runId": r.run_id,
                "startedAt": _utc(r.started_at).isoformat(),
                "finishedAt": _utc(r.finished_at).isoformat() if r.finished_at else None,
                "status": r.status,
                "checkpoint": r.checkpoint,
                "error": r.error,
            }
            for r in rows
        ]
    }


@router.get("/collection/sources")
def collection_sources() -> dict[str, Any]:
    """The read-only allowlist; api versions not verified stay marked as such."""
    return {
        "sources": [
            {
                "id": r.source_id,
                "method": r.method,
                "apiVersion": r.api_version,
                "apiVersionStatus": r.api_version_status,
                "readOnlyQueryPost": r.read_only_query_post,
            }
            for r in RULES
        ]
    }
