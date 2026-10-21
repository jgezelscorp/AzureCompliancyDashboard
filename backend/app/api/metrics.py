"""Read-only metrics, history and collection-status endpoints (no write operations).

Every endpoint requires an Entra bearer token. Metrics are computed only from evidence of
subscriptions that are onboarded AND readable by the signed-in viewer under Azure RBAC
(decided with the viewer's delegated token); collector-wide aggregates are never returned to a
viewer who cannot see every onboarded scope. Unverifiable authorization fails closed.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import current_principal
from app.auth.scope import AuthorizedScopes, authorized_scopes
from app.auth.tokens import Principal
from app.azure.allowlist import RULES
from app.config import Settings, get_settings
from app.database import get_session
from app.db import CollectionRunRow, MachineRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow
from app.metrics import views
from app.metrics.engine import FAMILIES, compute
from app.metrics.store import load_bundle, snapshot_to_dict
from app.models import EvidenceBundle
from app.sink.outbox import delivery_summary

router = APIRouter(prefix="/api/v1", tags=["metrics"])

Family = Literal["AzureWindowsBaseline", "CISWindowsSecurityBaseline"]
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ScopesDep = Annotated[AuthorizedScopes, Depends(authorized_scopes)]
PrincipalDep = Annotated[Principal, Depends(current_principal)]

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


def _scope_info(scopes: AuthorizedScopes) -> dict[str, Any]:
    return {
        "authorizedSubscriptions": len(scopes.subscription_ids),
        "onboardedSubscriptions": len(scopes.registered),
        "partial": scopes.partial,
    }


def _subscription_of(machine_id: str) -> str | None:
    parts = machine_id.lower().split("/")
    return parts[2] if len(parts) > 2 and parts[1] == "subscriptions" else None


def _newest(session: Session) -> MetricSnapshotRow | None:
    return session.scalars(
        select(MetricSnapshotRow).order_by(MetricSnapshotRow.snapshot_at.desc()).limit(1)
    ).first()


def _authorized_bundle(
    session: Session,
    scopes: AuthorizedScopes,
    settings: Settings,
    subscription_id: str | None = None,
) -> tuple[MetricSnapshotRow, EvidenceBundle, timedelta] | None:
    """Latest evidence restricted to the viewer's scopes; None when nothing was collected."""
    snap = _newest(session)
    if snap is None:
        return None
    allowed = scopes.subscription_ids
    if subscription_id is not None:
        allowed = allowed & {subscription_id.lower()}
    run = session.get(CollectionRunRow, snap.run_id)
    bundle = load_bundle(
        session,
        _utc(snap.snapshot_at),
        machines_seen_since=_utc(run.started_at) if run else None,
        subscription_ids=allowed,
    )
    return snap, bundle, timedelta(hours=settings.freshness_hours)


@router.get("/metrics/latest")
def latest_metrics(session: SessionDep, settings: SettingsDep, scopes: ScopesDep) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings)
    if found is None:
        return {
            "snapshotAt": None,
            "dataStale": True,
            "families": [],
            "labels": LABELS,
            "scope": _scope_info(scopes),
        }
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    families = []
    for family in FAMILIES:
        m = compute(bundle, family, at, stale_after)
        families.append(
            {
                "snapshotId": snap.id,
                "runId": snap.run_id,
                "snapshotAt": at.isoformat(),
                "collectionStatus": snap.collection_status,
                "family": family,
                "policyCompliance": m["policyCompliance"],
                "checkPassRate": m["checkPassRate"],
                "coverage": m["coverage"],
                "note": FAMILY_NOTES.get(family),
            }
        )
    return {
        "snapshotAt": at.isoformat(),
        "dataStale": _now() - at > stale_after,
        "freshnessHours": settings.freshness_hours,
        "families": families,
        "labels": LABELS,
        "scope": _scope_info(scopes),
    }


@router.get("/metrics/scopes")
def metrics_scopes(session: SessionDep, settings: SettingsDep, scopes: ScopesDep) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings)
    if found is None:
        return {"snapshotAt": None, "scopes": [], "scope": _scope_info(scopes)}
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    return {
        "snapshotAt": at.isoformat(),
        "scopes": views.scopes(bundle, FAMILIES, at, stale_after),
        "scope": _scope_info(scopes),
    }


@router.get("/metrics/categories")
def metrics_categories(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    family: Family,
    subscription_id: Annotated[str | None, Query(alias="subscriptionId")] = None,
) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings, subscription_id)
    if found is None:
        return {"snapshotAt": None, "family": family, "categories": []}
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    return {
        "snapshotAt": at.isoformat(),
        "family": family,
        "categories": views.categories(bundle, family, at, stale_after),
    }


@router.get("/metrics/checks")
def metrics_checks(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    family: Family,
    category: str,
    subscription_id: Annotated[str | None, Query(alias="subscriptionId")] = None,
) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings, subscription_id)
    if found is None:
        return {"snapshotAt": None, "family": family, "category": category, "checks": []}
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    return {
        "snapshotAt": at.isoformat(),
        "family": family,
        "category": category,
        "checks": views.checks(bundle, family, category, at, stale_after),
    }


@router.get("/metrics/checks/machines")
def metrics_check_machines(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    family: Family,
    check_key: Annotated[str, Query(alias="checkKey")],
    subscription_id: Annotated[str | None, Query(alias="subscriptionId")] = None,
) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings, subscription_id)
    if found is None:
        return {"snapshotAt": None, "family": family, "checkKey": check_key, "machines": []}
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    return {
        "snapshotAt": at.isoformat(),
        "family": family,
        "checkKey": check_key,
        "machines": views.check_machines(bundle, family, check_key, at, stale_after),
    }


def _zero_counts() -> dict[str, int]:
    return {"machines": 0, "fresh": 0, "green": 0}


@router.get("/metrics/history")
def metrics_history(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    family: Family | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Sampled history. Collector-wide aggregates are included only for viewers who can see
    every onboarded and every collected scope; others get machine-level counts of their own
    scopes."""
    q = select(MetricSnapshotRow)
    if family:
        q = q.where(MetricSnapshotRow.family == family)
    if since:
        q = q.where(MetricSnapshotRow.snapshot_at >= _utc(since))
    if until:
        q = q.where(MetricSnapshotRow.snapshot_at <= _utc(until))
    rows = list(
        reversed(
            session.scalars(q.order_by(MetricSnapshotRow.snapshot_at.desc()).limit(limit)).all()
        )
    )
    full = not scopes.partial and set(settings.subscription_ids) <= scopes.subscription_ids
    counts: dict[int, dict[str, int]] = {r.id: _zero_counts() for r in rows}
    if rows:
        machine_rows = session.execute(
            select(
                MachineStatusSnapshotRow.snapshot_id,
                MachineStatusSnapshotRow.machine_id,
                MachineStatusSnapshotRow.evidence_quality,
                MachineStatusSnapshotRow.green,
            ).where(MachineStatusSnapshotRow.snapshot_id.in_(list(counts)))
        )
        for snapshot_id, machine_id, quality, green in machine_rows:
            if _subscription_of(machine_id) not in scopes.subscription_ids:
                continue
            c = counts[snapshot_id]
            c["machines"] += 1
            c["fresh"] += quality == "Fresh"
            c["green"] += bool(green)
    points = []
    for r in rows:
        point: dict[str, Any] = {
            "snapshotId": r.id,
            "runId": r.run_id,
            "snapshotAt": _utc(r.snapshot_at).isoformat(),
            "collectionStatus": r.collection_status,
            "family": r.family,
            "machineSummary": counts[r.id],
        }
        if full:
            point.update(snapshot_to_dict(r))
        points.append(point)
    return {
        "points": points,
        "aggregatesIncluded": full,
        "samplingNote": "Samples at collection times; not continuous assessment.",
        "labels": LABELS,
        "scope": _scope_info(scopes),
    }


@router.get("/metrics/machines")
def machine_statuses(
    session: SessionDep,
    scopes: ScopesDep,
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
        return {"snapshotAt": None, "family": family, "machines": [], "total": 0}
    base = (
        select(MachineStatusSnapshotRow, MachineRow)
        .join(MachineRow, MachineRow.machine_id == MachineStatusSnapshotRow.machine_id)
        .where(
            MachineStatusSnapshotRow.snapshot_id == snap.id,
            MachineRow.subscription_id.in_(scopes.subscription_ids),
        )
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.execute(
        base.order_by(MachineStatusSnapshotRow.machine_id).limit(limit).offset(offset)
    ).all()
    return {
        "snapshotAt": _utc(snap.snapshot_at).isoformat(),
        "family": family,
        "total": total,
        "machines": [
            {
                "machineId": s.machine_id,
                "name": m.name,
                "kind": m.kind,
                "subscriptionId": m.subscription_id.lower(),
                "evidenceQuality": s.evidence_quality,
                "reportedState": s.reported_state,
                "green": s.green,
            }
            for s, m in rows
        ],
    }


@router.get("/collection/runs")
def collection_runs(
    session: SessionDep, _: ScopesDep, limit: Annotated[int, Query(ge=1, le=200)] = 20
) -> dict[str, Any]:
    """Run status only; error text and checkpoints can name unauthorized scopes and are omitted."""
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
                "hasError": r.error is not None,
            }
            for r in rows
        ]
    }


@router.get("/collection/sink")
def collection_sink(session: SessionDep, settings: SettingsDep, _: ScopesDep) -> dict[str, Any]:
    """Optional Log Analytics delivery status. Counts and ages only; it never reflects on the
    validity of the PostgreSQL collection, which is judged by /collection/runs."""
    if not settings.logs_sink_enabled:
        return {"enabled": False}
    return {"enabled": True, **delivery_summary(session, _now())}


@router.get("/collection/sources")
def collection_sources(_: PrincipalDep) -> dict[str, Any]:
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
