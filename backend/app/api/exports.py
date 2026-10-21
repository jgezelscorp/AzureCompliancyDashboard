"""Authorized CSV/PDF export jobs (I09).

Exports use exactly the data the UI shows: the newest snapshot, filtered to scopes the signed-in
viewer can read *right now*. Authorization is re-verified with a fresh delegated token on create
AND on download; artifacts are short-lived, owner-bound, served only through authenticated
requests (no public/shared links) and purged after expiry. Every action writes an audit event
without artifact content or secrets.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.metrics import (
    FAMILY_NOTES,
    LABELS,
    Family,
    PrincipalDep,
    ScopesDep,
    SessionDep,
    SettingsDep,
    _authorized_bundle,
    _now,
    _utc,
)
from app.auth.scope import AuthorizedScopes
from app.auth.tokens import Principal
from app.config import Settings
from app.db import MachineRow
from app.db_exports import ExportAuditRow, ExportJobRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow
from app.exporters import PdfDoc, build_csv, pdf_text
from app.metrics import views
from app.metrics.engine import FAMILIES, compute

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])

ARTIFACT_TTL = timedelta(minutes=15)
MAX_ROWS = 5000
MAX_ARTIFACT_BYTES = 5_000_000
MAX_ACTIVE_JOBS_PER_USER = 10
SYNTHETIC_CIS_NOTE = (
    "CIS Windows evidence is validated with synthetic fixtures only; it is not a verified live "
    "CIS integration until checked against an authorized actual report."
)
NO_CERT_NOTE = (
    "This export is not a CIS, ISO, NIS2 or DORA certification or attestation, and no data is "
    "not compliance."
)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format: Literal["csv", "pdf"]
    family: Family
    template: Literal["executive", "technical"] = "technical"
    dataset: Literal["checks", "machines"] = "checks"
    subscription_id: str | None = Field(default=None, alias="subscriptionId", max_length=36)


def _audit(session: Session, oid: str, event: str, job_id: str | None, detail: str = "") -> None:
    session.add(
        ExportAuditRow(at=_now(), actor_oid=oid, event=event, job_id=job_id, detail=detail[:500])
    )


def purge_expired(session: Session, now: datetime | None = None) -> int:
    """Delete expired artifacts (rows are kept as tombstones). Safe to call from a scheduler."""
    now = now or _now()
    ids = list(
        session.scalars(
            select(ExportJobRow.job_id).where(
                ExportJobRow.expires_at <= now, ExportJobRow.artifact.is_not(None)
            )
        )
    )
    if ids:
        session.execute(
            update(ExportJobRow)
            .where(ExportJobRow.job_id.in_(ids))
            .values(artifact=None, status="expired")
            .execution_options(synchronize_session=False)
        )
        for jid in ids:
            _audit(session, "system", "export.purged", jid)
    # tombstones are dropped one day after expiry; audit rows remain
    session.execute(
        delete(ExportJobRow)
        .where(ExportJobRow.expires_at <= now - timedelta(days=1))
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return len(ids)


def _disclosures(
    scopes: AuthorizedScopes,
    req: ExportRequest,
    snapshot_at: datetime,
    freshness_hours: int,
    stale: bool,
    generated: datetime,
) -> list[str]:
    scope_text = (
        f"Scope: {len(scopes.subscription_ids)} of {len(scopes.registered)} onboarded "
        "subscription(s) readable by the exporting user under Azure RBAC at generation time"
        + (f"; filtered to {req.subscription_id.lower()}" if req.subscription_id else "")
        + (". Partial: other onboarded scopes are not included." if scopes.partial else ".")
    )
    return [
        scope_text,
        f"Snapshot: {snapshot_at.isoformat()} (generated {generated.isoformat()}). "
        "Sampled at collection time, not continuous assessment.",
        f"Freshness: reports older than {freshness_hours} hours are stale and never counted as "
        + ("passing. THE SNAPSHOT IS STALE." if stale else "passing."),
        f"Baseline: {req.family}. {FAMILY_NOTES.get(req.family, '')}",
        SYNTHETIC_CIS_NOTE,
        NO_CERT_NOTE,
        LABELS[0],
        "Artifact expires shortly after creation and is re-authorized on every download.",
    ]


def _csv_checks(
    bundle: Any, req: ExportRequest, at: datetime, stale_after: timedelta
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for cat in views.categories(bundle, req.family, at, stale_after):
        for c in views.checks(bundle, req.family, cat["category"], at, stale_after):
            rows.append(
                [
                    cat["category"],
                    c["checkKey"],
                    c["name"],
                    c["severity"],
                    c["benchmarkControlId"],
                    c["machinesFailed"],
                    c["machinesPassed"],
                    f"{c['categorySource']} (app rules v{c['categoryRuleVersion']})"
                    if c["categorySource"] == "derived"
                    else c["categorySource"],
                ]
            )
    return rows


def _machine_rows(
    session: Session, snap: MetricSnapshotRow, req: ExportRequest, allowed: frozenset[str]
) -> list[list[Any]]:
    if req.subscription_id:
        allowed = allowed & {req.subscription_id.lower()}
    fam_snap = session.scalars(
        select(MetricSnapshotRow).where(
            MetricSnapshotRow.run_id == snap.run_id, MetricSnapshotRow.family == req.family
        )
    ).first()
    if fam_snap is None:
        return []
    q = (
        select(MachineStatusSnapshotRow, MachineRow)
        .join(MachineRow, MachineRow.machine_id == MachineStatusSnapshotRow.machine_id)
        .where(
            MachineStatusSnapshotRow.snapshot_id == fam_snap.id,
            func.lower(MachineRow.subscription_id).in_(allowed),
        )
        .order_by(MachineStatusSnapshotRow.machine_id)
        .limit(MAX_ROWS + 1)
    )
    return [
        [
            m.name,
            m.subscription_id.lower(),
            m.kind,
            s.evidence_quality,
            "Not assessed" if s.evidence_quality != "Fresh" else (s.reported_state or "No data"),
        ]
        for s, m in session.execute(q)
    ]


def _fmt(metric: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in metric.items() if not isinstance(v, dict | list))


def _pdf(
    req: ExportRequest,
    bundle: Any,
    disclosures: list[str],
    at: datetime,
    stale_after: timedelta,
) -> tuple[bytes, int, bool]:
    doc = PdfDoc()
    title = "Executive summary" if req.template == "executive" else "Technical report"
    doc.add("title", f"Azure Policy / Machine Configuration reporting - {title}")
    doc.add("h", "Disclosures")
    for d in disclosures:
        doc.add("p", "- " + d)
    families = FAMILIES if req.template == "executive" else (req.family,)
    doc.add("h", "Metrics (kept separate; never combined)")
    for f in families:
        m = compute(bundle, f, at, stale_after)
        doc.add("p", f"{f}")
        for key, label in (
            ("policyCompliance", "Policy compliance"),
            ("checkPassRate", "Check pass rate"),
            ("coverage", "Coverage"),
        ):
            doc.add("mono", f"  {label}: {_fmt(m[key])}")
    rows = 0
    truncated = False
    if req.template == "technical":
        doc.add("h", f"Categories and checks - {req.family}")
        for cat in views.categories(bundle, req.family, at, stale_after):
            doc.add("p", f"{cat['category']}: {cat['passed']}/{cat['total']} passed")
            for c in views.checks(bundle, req.family, cat["category"], at, stale_after):
                if rows >= MAX_ROWS:
                    truncated = True
                    break
                rows += 1
                doc.add(
                    "mono",
                    f"  {c['benchmarkControlId'] or c['checkKey']} | {c['name']} | "
                    f"failing machines {c['machinesFailed']} | passing {c['machinesPassed']}",
                )
        if truncated:
            doc.add("p", f"Truncated at {MAX_ROWS} checks.")
    return doc.render(), rows, truncated


def _job_dict(j: ExportJobRow) -> dict[str, Any]:
    return {
        "jobId": j.job_id,
        "kind": j.kind,
        "family": j.family,
        "subscriptionId": j.subscription_filter,
        "status": j.status,
        "snapshotAt": _utc(j.snapshot_at).isoformat() if j.snapshot_at else None,
        "createdAt": _utc(j.created_at).isoformat(),
        "expiresAt": _utc(j.expires_at).isoformat(),
        "rowCount": j.row_count,
        "truncated": j.truncated,
        "filename": j.filename,
        "scopeCount": len([s for s in j.scope_subscription_ids.split(",") if s]),
    }


@router.post("", status_code=201)
def create_export(
    req: ExportRequest,
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
) -> dict[str, Any]:

    oid = scopes.principal.object_id
    sub = req.subscription_id.lower() if req.subscription_id else None
    if sub is not None and sub not in scopes.subscription_ids:
        _audit(session, oid, "export.denied", None, "create: scope not authorized")
        session.commit()
        raise HTTPException(403, "Not authorized for the requested scope")
    purge_expired(session)
    active = session.scalar(
        select(func.count())
        .select_from(ExportJobRow)
        .where(ExportJobRow.owner_oid == oid, ExportJobRow.artifact.is_not(None))
    )
    if (active or 0) >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, "Too many active exports; wait for existing ones to expire")
    found = _authorized_bundle(session, scopes, settings, sub)
    if found is None:
        raise HTTPException(409, "No collected evidence to export")
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    now = _now()
    stale = now - at > stale_after
    disclosures = _disclosures(scopes, req, at, settings.freshness_hours, stale, now)
    truncated = False
    if req.format == "csv":
        if req.dataset == "checks":
            header = [
                "Category",
                "CheckKey",
                "Name",
                "Severity",
                "ControlId",
                "MachinesFailing",
                "MachinesPassing",
                "CategorySource",
            ]
            data_rows = _csv_checks(bundle, req, at, stale_after)
        else:
            header = ["Machine", "SubscriptionId", "Kind", "EvidenceQuality", "ReportedState"]
            data_rows = _machine_rows(session, snap, req, scopes.subscription_ids)
        truncated = len(data_rows) > MAX_ROWS
        data_rows = data_rows[:MAX_ROWS]
        if truncated:
            disclosures.append(f"Truncated at {MAX_ROWS} rows.")
        artifact = build_csv(disclosures, header, data_rows)
        row_count, ctype, ext, kind = (
            len(data_rows),
            "text/csv; charset=utf-8",
            "csv",
            f"csv-{req.dataset}",
        )
    else:
        artifact, row_count, truncated = _pdf(req, bundle, disclosures, at, stale_after)
        ctype, ext, kind = "application/pdf", "pdf", f"pdf-{req.template}"
    if len(artifact) > MAX_ARTIFACT_BYTES:
        raise HTTPException(413, "Export exceeds the size limit; narrow the scope filter")
    job_id = str(uuid.uuid4())
    job = ExportJobRow(
        job_id=job_id,
        owner_oid=oid,
        tenant_id=scopes.principal.tenant_id,
        kind=kind,
        family=req.family,
        subscription_filter=sub,
        scope_subscription_ids=",".join(sorted(scopes.subscription_ids)),
        snapshot_id=snap.id,
        snapshot_at=at,
        status="completed",
        row_count=row_count,
        truncated=truncated,
        content_type=ctype,
        filename=f"azure-policy-{req.family}-{job_id[:8]}.{ext}",
        artifact=artifact,
        created_at=now,
        expires_at=now + ARTIFACT_TTL,
    )
    session.add(job)
    _audit(session, oid, "export.created", job_id, f"{kind} family={req.family} rows={row_count}")
    session.commit()
    return _job_dict(job)


def _owned_job(session: Session, principal: Principal, job_id: str) -> ExportJobRow:
    job = session.get(ExportJobRow, job_id)
    if job is None or job.owner_oid != principal.object_id or job.tenant_id != principal.tenant_id:
        raise HTTPException(404, "Export not found")
    return job


@router.get("")
def list_exports(session: SessionDep, principal: PrincipalDep) -> dict[str, Any]:
    purge_expired(session)
    rows = session.scalars(
        select(ExportJobRow)
        .where(
            ExportJobRow.owner_oid == principal.object_id,
            ExportJobRow.tenant_id == principal.tenant_id,
        )
        .order_by(ExportJobRow.created_at.desc())
        .limit(50)
    ).all()
    return {"jobs": [_job_dict(j) for j in rows]}


@router.get("/{job_id}")
def export_status(job_id: str, session: SessionDep, principal: PrincipalDep) -> dict[str, Any]:
    job = _owned_job(session, principal, job_id)
    if job.artifact is not None and _utc(job.expires_at) <= _now():
        purge_expired(session)
        session.refresh(job)
    return _job_dict(job)


@router.get("/{job_id}/download")
def download_export(
    job_id: str, session: SessionDep, scopes: ScopesDep, settings: SettingsDep
) -> Response:
    # ScopesDep already performed a fresh delegated Azure RBAC check for this request.
    oid = scopes.principal.object_id
    job = _owned_job(session, scopes.principal, job_id)
    if job.artifact is None or _utc(job.expires_at) <= _now():
        purge_expired(session)
        _audit(session, oid, "export.expired", job_id, "download after expiry")
        session.commit()
        raise HTTPException(410, "Export expired; create a new export")
    needed = {s for s in job.scope_subscription_ids.split(",") if s}
    if not needed <= scopes.subscription_ids:
        _audit(session, oid, "export.denied", job_id, "download: authorization changed")
        session.commit()
        raise HTTPException(403, "Authorization changed; create a new export")
    _audit(session, oid, "export.downloaded", job_id, job.kind)
    session.commit()
    return Response(
        content=job.artifact,
        media_type=job.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_text(job.filename)}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["Settings", "router"]
