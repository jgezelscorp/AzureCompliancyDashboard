"""Estate-wide Azure Policy views (read-only).

Every endpoint is restricted to the subscriptions the signed-in viewer is authorized for
(Azure RBAC, decided with the viewer's delegated token) **before** anything is aggregated, so no
count, percentage, trend or list can reveal an unauthorized scope. Large lists are paginated and
the application gzips responses. See docs/policy-estate.md for the metric definitions.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.metrics import LABELS, Family, _authorized_bundle, _scope_info
from app.auth.scope import AuthorizedScopes, authorized_scopes
from app.config import Settings, get_settings
from app.database import get_session
from app.db import MachineRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow
from app.db_policy import DefenderSnapshotRow, EstateSnapshotRow
from app.metrics import policy, views
from app.metrics.engine import FAMILIES, compute
from app.models import EvidenceBundle

router = APIRouter(prefix="/api/v1/policy", tags=["policy-estate"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ScopesDep = Annotated[AuthorizedScopes, Depends(authorized_scopes)]

ESTATE_LABELS = [
    *LABELS,
    "Azure Policy compliance % = Compliant / (Compliant + NonCompliant) policy evaluations; "
    "Exempt and Unknown evaluations are shown apart and never counted as compliant.",
    "There is no composite risk score. Every figure shows its own numerator, denominator and "
    "grain.",
    "Groups with nothing to count show 'no data', never 100 %.",
]
MAX_TREND_POINTS = 400


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def state_filter(
    sub: Annotated[list[str] | None, Query(description="Subscription id")] = None,
    rg: Annotated[list[str] | None, Query(description="Resource group")] = None,
    loc: Annotated[list[str] | None, Query(description="Location")] = None,
    rtype: Annotated[list[str] | None, Query(description="Resource type")] = None,
    initiative: Annotated[list[str] | None, Query()] = None,
    assignment: Annotated[list[str] | None, Query()] = None,
    definition: Annotated[list[str] | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    effect: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
    tag: Annotated[list[str] | None, Query(description="key:value")] = None,
    max_age_hours: Annotated[int | None, Query(alias="maxAgeHours", ge=0)] = None,
    min_age_hours: Annotated[int | None, Query(alias="minAgeHours", ge=0)] = None,
    q: Annotated[str, Query(max_length=200)] = "",
) -> policy.StateFilter:
    def t(v: list[str] | None) -> tuple[str, ...]:
        return tuple(x.lower() if x else x for x in (v or []))

    def keep(v: list[str] | None) -> tuple[str, ...]:
        return tuple(v or [])

    return policy.StateFilter(
        subscription=t(sub),
        resource_group=t(rg),
        location=t(loc),
        resource_type=t(rtype),
        initiative=t(initiative),
        assignment=t(assignment),
        definition=t(definition),
        state=keep(state),
        category=keep(category),
        effect=t(effect),
        severity=t(severity),
        tag=keep(tag),
        max_age_hours=max_age_hours,
        min_age_hours=min_age_hours,
        q=q.strip(),
    )


FilterDep = Annotated[policy.StateFilter, Depends(state_filter)]


def _estate(
    session: Session, scopes: AuthorizedScopes
) -> tuple[policy.EstateData, datetime | None]:
    """Authorized evidence only: rows of other subscriptions are never loaded."""
    data = policy.load_estate(session, scopes.subscription_ids)
    newest = max((s["ts"] for s in data.states), default=None)
    return data, newest


def _snapshot_time(session: Session, scopes: AuthorizedScopes) -> datetime | None:
    if not scopes.subscription_ids:
        return None
    at = session.scalars(
        select(EstateSnapshotRow.snapshot_at)
        .where(EstateSnapshotRow.subscription_id.in_(scopes.subscription_ids))
        .order_by(EstateSnapshotRow.snapshot_at.desc())
        .limit(1)
    ).first()
    return _utc(at) if at else None


def _series(
    session: Session, scopes: AuthorizedScopes, settings: Settings, limit: int = MAX_TREND_POINTS
) -> dict[str, Any]:
    """Per-run sums over the viewer's authorized subscriptions (same grain as the headline)."""
    rows = session.scalars(
        select(EstateSnapshotRow)
        .where(EstateSnapshotRow.subscription_id.in_(scopes.subscription_ids))
        .order_by(EstateSnapshotRow.snapshot_at.desc())
        .limit(limit * max(1, len(scopes.subscription_ids)))
    ).all()
    runs: dict[int, dict[str, Any]] = {}
    for r in rows:
        m: Any = r.metrics
        h = m.get("headline", {})
        point = runs.setdefault(
            r.run_id,
            {
                "runId": r.run_id,
                "at": _utc(r.snapshot_at),
                "status": r.collection_status,
                "subscriptions": 0,
                "compliant": 0,
                "nonCompliant": 0,
                "exempt": 0,
                "other": 0,
                "evaluations": 0,
                "resources": 0,
                "nonCompliantResources": 0,
                "resourcesCounted": 0,
                "resourcesFullyCompliant": 0,
                "highImpactFailingPolicies": 0,
                "enforcementFailingPolicies": 0,
                "regressions": 0,
                "recoveries": 0,
                "newNonCompliant": 0,
            },
        )
        point["subscriptions"] += 1
        for k in (
            "compliant",
            "nonCompliant",
            "exempt",
            "other",
            "evaluations",
            "resources",
            "nonCompliantResources",
            "resourcesCounted",
            "resourcesFullyCompliant",
            "highImpactFailingPolicies",
            "enforcementFailingPolicies",
        ):
            point[k] += int(h.get(k) or 0)
        ch = m.get("changes") or {}
        for k in ("regressions", "recoveries", "newNonCompliant"):
            point[k] += int(ch.get(k) or 0)
    points = sorted(runs.values(), key=lambda p: p["at"])[-limit:]
    gap_after = timedelta(hours=settings.collection_interval_hours * 2)
    prev: datetime | None = None
    out = []
    for p in points:
        p["percent"] = policy.pct(p["compliant"], p["compliant"] + p["nonCompliant"])
        p["resourcePercent"] = policy.pct(p["resourcesFullyCompliant"], p["resourcesCounted"])
        p["gapBefore"] = prev is not None and p["at"] - prev > gap_after
        p["at"] = p["at"].isoformat()
        prev = _utc(datetime.fromisoformat(p["at"]))
        out.append(p)
    return {
        "points": out,
        "samples": len(out),
        "intervalHours": settings.collection_interval_hours,
        "note": (
            f"{len(out)} sample{'s' if len(out) != 1 else ''} so far (collected every "
            f"{settings.collection_interval_hours} h); trends are sampled, not continuous."
        ),
    }


def _delta(points: list[dict[str, Any]], key: str) -> dict[str, Any]:
    vals = [p.get(key) for p in points]
    cur = vals[-1] if vals else None
    prev = vals[-2] if len(vals) > 1 else None
    delta = None if cur is None or prev is None else round(cur - prev, 2)
    return {
        "previous": prev,
        "delta": delta,
        "previousAt": points[-2]["at"] if len(points) > 1 else None,
        "sparkline": [v for v in vals[-30:]],
    }


def _kpi(
    kpi_id: str,
    label: str,
    value: float | int | None,
    unit: Literal["percent", "count"],
    *,
    numerator: int | None,
    denominator: int | None,
    grain: str,
    formula: str,
    drill: dict[str, Any] | None,
    series_key: str | None = None,
    points: list[dict[str, Any]] | None = None,
    good: Literal["up", "down"] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    trend = _delta(points or [], series_key) if series_key else _delta([], "x")
    return {
        "id": kpi_id,
        "label": label,
        "value": value,
        "unit": unit,
        "status": "ok" if value is not None else "no-data",
        "numerator": numerator,
        "denominator": denominator,
        "grain": grain,
        "formula": formula,
        "drill": drill,
        "goodDirection": good,
        "note": note,
        **trend,
    }


def _machine_kpis(
    session: Session, scopes: AuthorizedScopes, settings: Settings, full_history: bool
) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings)
    if found is None:
        return {"available": False}
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    m = compute(bundle, "AzureWindowsBaseline", at, stale_after)
    spark: list[float | None] = []
    if full_history:
        hist = session.scalars(
            select(MetricSnapshotRow)
            .where(MetricSnapshotRow.family == "AzureWindowsBaseline")
            .order_by(MetricSnapshotRow.snapshot_at.desc())
            .limit(30)
        ).all()
        spark = [
            (r.check_pass_rate or {}).get("percent")  # type: ignore[misc]
            for r in reversed(hist)
        ]
    return {
        "available": True,
        "snapshotAt": at.isoformat(),
        "family": "AzureWindowsBaseline",
        "checkPassRate": m["checkPassRate"],
        "coverage": m["coverage"],
        "policyCompliance": m["policyCompliance"],
        "sparkline": spark,
        "sparklineNote": None
        if full_history
        else "History hidden: your access does not cover every onboarded scope.",
    }


def _defender(session: Session, scopes: AuthorizedScopes) -> dict[str, Any]:
    if not scopes.subscription_ids:
        return {"available": False, "reason": "no authorized scope"}
    rows = session.scalars(
        select(DefenderSnapshotRow)
        .where(DefenderSnapshotRow.subscription_id.in_(scopes.subscription_ids))
        .order_by(DefenderSnapshotRow.snapshot_at.desc())
        .limit(20 * len(scopes.subscription_ids))
    ).all()
    latest: dict[str, DefenderSnapshotRow] = {}
    for r in rows:
        latest.setdefault(r.subscription_id, r)
    if not latest:
        return {"available": False, "reason": "not collected yet"}
    out = []
    for sub, r in sorted(latest.items()):
        out.append(
            {
                "subscriptionId": sub,
                "available": r.available,
                "reason": r.reason,
                "secureScore": r.secure_score,
                "standards": (r.standards or [])[:30],
                "snapshotAt": _utc(r.snapshot_at).isoformat(),
            }
        )
    return {
        "available": any(x["available"] for x in out),
        "subscriptions": out,
        "note": "Defender for Cloud data is shown separately and is never merged into Azure "
        "Policy compliance.",
    }


def _summary(
    head: dict[str, Any],
    top: list[dict[str, Any]],
    init_rows: list[dict[str, Any]],
    ex: dict[str, Any],
    fresh: dict[str, Any],
    samples: int,
    snapshot_at: datetime | None,
) -> list[str]:
    """Facts only, each sentence is a direct restatement of a number shown on the screen."""
    if head["evaluations"] == 0:
        return ["No Azure Policy evaluations have been collected for the authorized scopes yet."]
    lines = []
    when = snapshot_at.strftime("%Y-%m-%d %H:%M UTC") if snapshot_at else "unknown time"
    if head["percent"] is None:
        lines.append(f"As of {when}, no evaluation is Compliant or NonCompliant, so no % applies.")
    else:
        lines.append(
            f"As of {when}, {head['compliant']} of {head['compliant'] + head['nonCompliant']} "
            f"counted policy evaluations are compliant ({head['percent']} %); "
            f"{head['exempt']} exempt and {head['other']} not assessed/unknown are shown apart."
        )
    lines.append(
        f"{head['nonCompliantResources']} of {head['resources']} resources have at least one "
        f"non-compliant policy evaluation across {head['nonCompliantPolicies']} policies."
    )
    if top:
        t = top[0]
        lines.append(
            f"The most widespread failing policy is '{t['name']}' affecting "
            f"{t['affectedResources']} resources."
        )
    worst = [r for r in init_rows if r["percent"] is not None and r["nonCompliant"] > 0]
    if worst:
        w = min(worst, key=lambda r: r["percent"])
        lines.append(
            f"Lowest compliance by initiative: '{w['label']}' at {w['percent']} % "
            f"({w['compliant']} of {w['compliant'] + w['nonCompliant']})."
        )
    b = ex["buckets"]
    lines.append(
        f"{ex['total']} policy exemptions: {b['expiring30']} expire within 30 days, "
        f"{b['expired']} already expired."
    )
    if fresh["percent"] is not None:
        lines.append(
            f"{fresh['fresh']} of {fresh['evaluations']} evaluations are newer than "
            f"{fresh['thresholdHours']} h."
        )
    lines.append(f"Trend history: {samples} sample{'s' if samples != 1 else ''} so far.")
    return lines


@router.get("/overview")
def overview(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    flt: FilterDep,
) -> dict[str, Any]:
    now = _now()
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, now)
    head = policy.headline(states)
    series = _series(session, scopes, settings)
    pts = series["points"]
    # Trends are estate-wide; with an active filter we do not pretend the series is filtered.
    filtered = bool(flt.active)
    trend_pts = [] if filtered else pts
    exemptions = policy.exemption_summary(data.exemptions, now)
    fresh = policy.freshness(states, now, settings.freshness_hours)
    top = policy.top_policies(states, 10)
    init_rows = policy.breakdown(states, "initiative")
    full = not scopes.partial and set(settings.subscription_ids) <= scopes.subscription_ids
    machines = _machine_kpis(session, scopes, settings, full)
    severity_known = data.severity_metadata_present
    snapshot_at = _snapshot_time(session, scopes)
    nc_filter = {"state": ["NonCompliant"]}
    kpis = [
        _kpi(
            "policyCompliance",
            "Azure Policy compliance",
            head["percent"],
            "percent",
            numerator=head["compliant"],
            denominator=head["compliant"] + head["nonCompliant"],
            grain="policy evaluation",
            formula="Compliant / (Compliant + NonCompliant) policy evaluations. Exempt, "
            "Unknown and not-started evaluations are excluded and shown separately.",
            drill={"tab": "states", "params": {}},
            series_key="percent",
            points=trend_pts,
            good="up",
        ),
        _kpi(
            "nonCompliantResources",
            "Non-compliant resources",
            head["nonCompliantResources"],
            "count",
            numerator=head["nonCompliantResources"],
            denominator=head["resources"],
            grain="resource",
            formula="Distinct resources with at least one NonCompliant evaluation / distinct "
            "resources with any evaluation.",
            drill={"tab": "resources", "params": nc_filter},
            series_key="nonCompliantResources",
            points=trend_pts,
            good="down",
        ),
        _kpi(
            "resourceCompliance",
            "Fully compliant resources",
            head["resourcePercent"],
            "percent",
            numerator=head["resourcesFullyCompliant"],
            denominator=head["resourcesCounted"],
            grain="resource",
            formula="Resources with no NonCompliant evaluation / resources with at least one "
            "Compliant or NonCompliant evaluation.",
            drill={"tab": "resources", "params": {}},
            series_key="resourcePercent",
            points=trend_pts,
            good="up",
        ),
        _kpi(
            "highImpactFailing",
            "High-impact failing policies",
            head["highImpactFailingPolicies"] if severity_known else None,
            "count",
            numerator=head["highImpactFailingPolicies"] if severity_known else None,
            denominator=None,
            grain="policy definition",
            formula="Distinct failing policy definitions whose own metadata severity is High or "
            "Critical. Not available when no collected definition carries severity metadata.",
            drill={"tab": "policies", "params": {"severity": ["high", "critical"], **nc_filter}},
            series_key="highImpactFailingPolicies" if severity_known else None,
            points=trend_pts,
            good="down",
            note=None
            if severity_known
            else "No policy definition carries severity metadata; see enforcement-class count.",
        ),
        _kpi(
            "enforcementFailing",
            "Enforcement-class failing policies",
            head["enforcementFailingPolicies"],
            "count",
            numerator=head["enforcementFailingPolicies"],
            denominator=None,
            grain="policy definition",
            formula="Distinct failing policy definitions with effect deny, deployIfNotExists, "
            "modify or append.",
            drill={"tab": "policies", "params": {"effect": ["deny", "deployifnotexists"]}},
            series_key="enforcementFailingPolicies",
            points=trend_pts,
            good="down",
        ),
    ]
    if machines.get("available"):
        cpr = machines["checkPassRate"]
        cov = machines["coverage"]
        kpis.append(
            _kpi(
                "machineBaselinePassRate",
                "Machines baseline check pass rate",
                cpr["percent"],
                "percent",
                numerator=cpr["passed"],
                denominator=cpr["total"],
                grain="machine check (fresh reports only)",
                formula="Passed checks / all checks in Fresh Machine Configuration reports "
                f"(Azure Windows baseline). {cpr['reportsExcludedAsNotFresh']} reports "
                "excluded as not fresh.",
                drill={"page": "machines"},
                good="up",
            )
        )
        kpis.append(
            _kpi(
                "machineCoverage",
                "Machine baseline coverage",
                cov["freshReportPercent"],
                "percent",
                numerator=cov["freshReport"],
                denominator=cov["eligible"],
                grain="machine",
                formula="Eligible machines with a fresh report / eligible machines. "
                f"{cov['assigned']} assigned, {cov['usableReport']} with a usable report.",
                drill={"page": "machines"},
                good="up",
            )
        )
    b = exemptions["buckets"]
    kpis.append(
        _kpi(
            "exemptionsExpiring",
            "Exemptions expiring in 30 days",
            b["expiring30"],
            "count",
            numerator=b["expiring30"],
            denominator=exemptions["total"],
            grain="exemption",
            formula="Active exemptions whose expiry is within the next 30 days / all exemptions.",
            drill={"tab": "exemptions", "params": {}},
            good="down",
        )
    )
    kpis.append(
        _kpi(
            "evidenceFreshness",
            "Evidence freshness",
            fresh["percent"],
            "percent",
            numerator=fresh["fresh"],
            denominator=fresh["evaluations"],
            grain="policy evaluation",
            formula=f"Evaluations newer than {settings.freshness_hours} h / all evaluations.",
            drill={"tab": "states", "params": {"minAgeHours": settings.freshness_hours}},
            good="up",
        )
    )
    return {
        "snapshotAt": snapshot_at.isoformat() if snapshot_at else None,
        "scope": _scope_info(scopes),
        "filters": flt.active,
        "trendFiltered": filtered,
        "kpis": kpis,
        "headline": head,
        "summary": _summary(
            head, top, init_rows, exemptions, fresh, series["samples"], snapshot_at
        ),
        "samples": series["samples"],
        "sampleNote": series["note"],
        "defender": _defender(session, scopes),
        "machines": machines,
        "labels": ESTATE_LABELS,
    }


Dimension = Annotated[str, Query(description="initiative|assignment|definition|...|tag:<key>")]


@router.get("/breakdown")
def breakdown(
    session: SessionDep,
    scopes: ScopesDep,
    flt: FilterDep,
    dim: Dimension = "initiative",
    sort: str = "nonCompliant",
    desc: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if not policy.valid_dimension(dim):
        raise HTTPException(422, "Unknown dimension")
    if sort not in policy.SORTS:
        raise HTTPException(422, "Unknown sort")
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    rows = policy.breakdown(states, dim, sort, desc)
    return {
        "dimension": dim,
        "total": len(rows),
        "rows": rows[offset : offset + limit],
        "grain": "policy evaluation (resources / nonCompliantResources are distinct resources)",
        "formula": "percent = compliant / (compliant + nonCompliant)",
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
        "filters": flt.active,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/top-policies")
def top_policies(
    session: SessionDep,
    scopes: ScopesDep,
    flt: FilterDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    return {
        "rows": policy.top_policies(states, limit),
        "grain": "policy definition; counts are NonCompliant evaluations and distinct resources",
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
    }


STATE_SORTS = {
    "state": "state",
    "resource": "resourceName",
    "type": "rtype",
    "policy": "definitionName",
    "initiative": "initiativeName",
    "assignment": "assignmentName",
    "effect": "effect",
    "category": "category",
    "evaluated": "ts",
}


@router.get("/states")
def states_list(
    session: SessionDep,
    scopes: ScopesDep,
    flt: FilterDep,
    sort: str = "state",
    desc: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if sort not in STATE_SORTS:
        raise HTTPException(422, "Unknown sort")
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    key = STATE_SORTS[sort]
    order = {"NonCompliant": 0, "Compliant": 1, "Exempt": 2}
    states = (
        sorted(
            states,
            key=lambda s: order.get(s["state"], 3) if key == "state" else str(s[key] or "").lower(),
            reverse=desc,
        )
        if key != "ts"
        else sorted(states, key=lambda s: s["ts"], reverse=desc)
    )
    page = states[offset : offset + limit]
    return {
        "total": len(states),
        "limit": limit,
        "offset": offset,
        "tally": policy.tally(states),
        "rows": [
            {
                "resourceId": s["rid"],
                "resourceName": s["resourceName"],
                "resourceType": s["rtype"],
                "subscriptionId": s["sub"],
                "resourceGroup": s["rg"],
                "location": s["loc"],
                "policy": s["definitionName"],
                "definition": s["definition"],
                "assignment": s["assignmentName"],
                "assignmentId": s["assignment"],
                "initiative": s["initiativeName"],
                "initiativeId": s["initiative"],
                "state": s["state"],
                "effect": s["effect"],
                "category": s["category"],
                "severity": s["severity"],
                "evaluatedAt": s["ts"].isoformat(),
            }
            for s in page
        ],
        "grain": "policy evaluation",
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
        "filters": flt.active,
    }


RESOURCE_SORTS = {
    "nonCompliant": "nonCompliant",
    "failingPolicies": "failingPolicies",
    "evaluations": "evaluations",
    "name": "name",
    "type": "resourceType",
    "resourceGroup": "resourceGroup",
    "newest": "newestEvaluation",
}


@router.get("/resources")
def resources_list(
    session: SessionDep,
    scopes: ScopesDep,
    flt: FilterDep,
    sort: str = "nonCompliant",
    desc: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if sort not in RESOURCE_SORTS:
        raise HTTPException(422, "Unknown sort")
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    rows = policy.resource_rows(states)
    k = RESOURCE_SORTS[sort]
    rows.sort(
        key=lambda r: (
            str(r[k] or "").lower() if k in ("name", "resourceType", "resourceGroup") else r[k]
        ),
        reverse=desc,
    )
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "rows": rows[offset : offset + limit],
        "grain": "resource (rolled up from policy evaluations)",
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
        "filters": flt.active,
    }


@router.get("/resource")
def resource_detail(
    session: SessionDep,
    scopes: ScopesDep,
    resource_id: Annotated[str, Query(alias="id", max_length=1000)],
) -> dict[str, Any]:
    """One resource and every policy evaluation behind its row (authorized scopes only)."""
    data, _ = _estate(session, scopes)
    rid = resource_id.lower()
    mine = [s for s in data.states if s["rid"].lower() == rid]
    if not mine:
        raise HTTPException(404, "Resource not found in the authorized scopes")
    inv = data.resources.get(mine[0]["rid"], {})
    return {
        "resourceId": mine[0]["rid"],
        "name": mine[0]["resourceName"],
        "resourceType": mine[0]["rtype"],
        "subscriptionId": mine[0]["sub"],
        "resourceGroup": mine[0]["rg"],
        "location": mine[0]["loc"],
        "tags": inv.get("tags") or {},
        "tally": policy.tally(mine),
        "states": [
            {
                "policy": s["definitionName"],
                "definition": s["definition"],
                "assignment": s["assignmentName"],
                "initiative": s["initiativeName"],
                "state": s["state"],
                "effect": s["effect"],
                "category": s["category"],
                "severity": s["severity"],
                "evaluatedAt": s["ts"].isoformat(),
            }
            for s in sorted(mine, key=lambda s: (s["state"] != "NonCompliant", s["definitionName"]))
        ],
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
    }


@router.get("/exemptions")
def exemptions_list(
    session: SessionDep,
    scopes: ScopesDep,
    status: Annotated[Literal["all", "active", "expired"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    data, _ = _estate(session, scopes)
    out = policy.exemption_summary(data.exemptions, _now())
    items = [i for i in out["items"] if status == "all" or i["status"] == status]
    return {
        "buckets": out["buckets"],
        "total": out["total"],
        "filteredTotal": len(items),
        "items": items[offset : offset + limit],
        "grain": "exemption",
        "note": "Buckets are exclusive: <30, 30-59 and 60-89 days to expiry, plus expired.",
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
    }


@router.get("/trend")
def trend(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    limit: Annotated[int, Query(ge=2, le=MAX_TREND_POINTS)] = 120,
) -> dict[str, Any]:
    series = _series(session, scopes, settings, limit)
    return {
        **series,
        "grain": "policy evaluation; per-run sums over the authorized subscriptions",
        "gapNote": "A gap marker means the interval to the previous sample exceeded twice the "
        "collection interval; nothing is interpolated.",
    }


@router.get("/filters")
def filter_options(session: SessionDep, scopes: ScopesDep, settings: SettingsDep) -> dict[str, Any]:
    """Distinct values (with evaluation counts) for the filter controls."""
    data, _ = _estate(session, scopes)
    out: dict[str, Any] = {}
    for dim in policy.DIMENSIONS:
        rows = policy.breakdown(data.states, dim, "evaluations")[:200]
        out[dim] = [
            {"key": r["key"], "label": r["label"], "evaluations": r["evaluations"]} for r in rows
        ]
    out["tagKeys"] = list(settings.estate_tag_keys)
    out["states"] = sorted({s["state"] for s in data.states})
    return {"options": out, "snapshotAt": _iso(_snapshot_time(session, scopes))}


@router.get("/quality")
def quality(session: SessionDep, settings: SettingsDep, scopes: ScopesDep) -> dict[str, Any]:
    """What we cannot see: coverage and evidence limits of the estate view."""
    now = _now()
    data, newest = _estate(session, scopes)
    states = data.states
    resources_with_state = {s["rid"] for s in states}
    inventory = set(data.resources)
    no_eval = [r for r in inventory if r not in resources_with_state]
    types_no_eval: dict[str, int] = {}
    for rid in no_eval:
        t = (data.resources[rid].get("type") or "unknown").lower()
        types_no_eval[t] = types_no_eval.get(t, 0) + 1
    sev = sum(1 for d in data.definitions.values() if d.get("severity"))
    resolved = len(data.definitions)
    unresolved_cat = sum(1 for s in states if s["category"] == policy.UNCATEGORIZED)
    return {
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
        "scope": _scope_info(scopes),
        "freshness": policy.freshness(states, now, settings.freshness_hours),
        "evaluationStates": policy.tally(states),
        "inventory": {
            "resources": len(inventory),
            "withEvaluations": len(inventory & resources_with_state),
            "withoutEvaluations": len(no_eval),
            "withoutEvaluationsTopTypes": sorted(types_no_eval.items(), key=lambda kv: -kv[1])[:10],
            "note": "Inventory is limited to resources visible to Azure Resource Graph for the "
            "collector identity; resource types that Azure Policy does not evaluate cannot be "
            "assessed.",
        },
        "metadata": {
            "definitionsResolved": resolved,
            "definitionsWithSeverity": sev,
            "evaluationsUncategorized": unresolved_cat,
            "evaluations": len(states),
            "note": "Severity is only shown when the definition's own metadata carries it. "
            "Categories come from definition metadata, never guessed.",
        },
        "tags": {"keys": list(settings.estate_tag_keys)},
        "cisNotAssessed": (
            "CIS benchmark results are only shown for machines with an actual CIS guest "
            "assignment; otherwise they are 'not assessed'."
        ),
        "newestEvaluation": _iso(newest),
        "defender": _defender(session, scopes),
        "limits": [
            "Policy states are the latest evaluation per resource and policy; history is built "
            "from collection snapshots, not from Azure.",
            "Exempt, Unknown and not-started evaluations are excluded from compliance %.",
            "Resources that Azure Policy does not evaluate are not part of any denominator.",
        ],
    }


def _machine_scope(bundle: EvidenceBundle, kind: str | None) -> EvidenceBundle:
    if kind is None:
        return bundle
    ids = {m.machine_id for m in bundle.machines if m.kind == kind}
    return bundle.model_copy(
        update={
            "machines": [m for m in bundle.machines if m.machine_id in ids],
            "assignments": [a for a in bundle.assignments if a.machine_id in ids],
            "reports": [r for r in bundle.reports if r.machine_id in ids],
            "policy_states": [p for p in bundle.policy_states if p.resource_id in ids],
        }
    )


@router.get("/machines/coverage")
def machine_coverage(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    family: Family = "AzureWindowsBaseline",
) -> dict[str, Any]:
    found = _authorized_bundle(session, scopes, settings)
    if found is None:
        return {"snapshotAt": None, "family": family, "groups": [], "scope": _scope_info(scopes)}
    snap, bundle, stale_after = found
    at = _utc(snap.snapshot_at)
    groups = []
    for label, kind in (
        ("All machines", None),
        ("Azure VM", "AzureVM"),
        ("Arc machine", "ArcMachine"),
    ):
        b = _machine_scope(bundle, kind)
        m = compute(b, family, at, stale_after)
        groups.append(
            {
                "label": label,
                "kind": kind,
                "machines": len(b.machines),
                "coverage": m["coverage"],
                "checkPassRate": m["checkPassRate"],
                "policyCompliance": m["policyCompliance"],
            }
        )
    return {
        "snapshotAt": at.isoformat(),
        "family": family,
        "groups": groups,
        "grain": "machine (coverage), check (pass rate), policy evaluation (policy compliance)",
        "note": "Coverage, check pass rate and policy compliance are separate metrics.",
        "scope": _scope_info(scopes),
        "labels": LABELS,
    }


def _machine_subscription(machine_id: str) -> str | None:
    parts = machine_id.lower().split("/")
    return parts[2] if len(parts) > 2 and parts[1] == "subscriptions" else None


@router.get("/machines/detail")
def machine_detail(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    machine_id: Annotated[str, Query(alias="id", max_length=1000)],
) -> dict[str, Any]:
    sub = _machine_subscription(machine_id)
    if sub is None or sub not in scopes.subscription_ids:
        raise HTTPException(404, "Machine not found in the authorized scopes")
    row = session.scalars(select(MachineRow).where(MachineRow.machine_id == machine_id)).first()
    if row is None:
        row = next(
            (
                r
                for r in session.scalars(
                    select(MachineRow).where(MachineRow.subscription_id.in_([sub]))
                )
                if r.machine_id.lower() == machine_id.lower()
            ),
            None,
        )
    if row is None:
        raise HTTPException(404, "Machine not found in the authorized scopes")
    found = _authorized_bundle(session, scopes, settings, sub)
    families: list[dict[str, Any]] = []
    snapshot_at: str | None = None
    if found is not None:
        snap, bundle, stale_after = found
        at = _utc(snap.snapshot_at)
        snapshot_at = at.isoformat()
        ids = {row.machine_id}
        single = bundle.model_copy(
            update={
                "machines": [m for m in bundle.machines if m.machine_id in ids],
                "assignments": [a for a in bundle.assignments if a.machine_id in ids],
                "reports": [r for r in bundle.reports if r.machine_id in ids],
                "policy_states": [p for p in bundle.policy_states if p.resource_id in ids],
            }
        )
        for family in FAMILIES:
            fam_assign = [a for a in single.assignments if a.baseline_family == family]
            fam_reports = [r for r in single.reports if r.baseline_family == family]
            m = compute(single, family, at, stale_after)
            status = m["machines"][0] if m["machines"] else None
            families.append(
                {
                    "family": family,
                    "assigned": bool(fam_assign),
                    "assignments": [
                        {
                            "name": a.guest_configuration_name,
                            "version": a.guest_configuration_version,
                            "complianceStatus": a.compliance_status,
                            "lastChecked": _iso(a.last_compliance_status_checked),
                        }
                        for a in fam_assign
                    ],
                    "reports": [
                        {
                            "reportId": r.report_id,
                            "complianceStatus": r.compliance_status,
                            "endTime": r.end_time.isoformat(),
                            "checks": len(r.checks),
                        }
                        for r in fam_reports
                    ],
                    "evidenceQuality": status["evidenceQuality"] if status else None,
                    "reportedState": status["reportedState"] if status else None,
                    "checkPassRate": m["checkPassRate"],
                    "categories": views.categories(single, family, at, stale_after)
                    if fam_assign
                    else [],
                    "note": None
                    if fam_assign
                    else "No guest assignment for this family: not assessed.",
                }
            )
    data, _ = _estate(session, scopes)
    mine = [s for s in data.states if s["rid"].lower() == row.machine_id.lower()]
    hist = session.execute(
        select(MetricSnapshotRow.snapshot_at, MetricSnapshotRow.family, MachineStatusSnapshotRow)
        .join(
            MachineStatusSnapshotRow, MachineStatusSnapshotRow.snapshot_id == MetricSnapshotRow.id
        )
        .where(MachineStatusSnapshotRow.machine_id == row.machine_id)
        .order_by(MetricSnapshotRow.snapshot_at.desc())
        .limit(60)
    ).all()
    return {
        "machine": {
            "machineId": row.machine_id,
            "name": row.name,
            "kind": row.kind,
            "subscriptionId": row.subscription_id.lower(),
            "resourceGroup": row.resource_group,
            "location": row.location,
            "osName": row.os_name,
            "osBuild": row.os_build,
            "eligibility": row.eligibility,
            "tags": {
                k: v
                for k, v in (row.tags or {}).items()
                if k.lower() in {t.lower() for t in settings.estate_tag_keys}
            },
        },
        "snapshotAt": snapshot_at,
        "families": families,
        "policy": {
            "tally": policy.tally(mine),
            "states": [
                {
                    "policy": s["definitionName"],
                    "initiative": s["initiativeName"],
                    "state": s["state"],
                    "effect": s["effect"],
                    "evaluatedAt": s["ts"].isoformat(),
                }
                for s in sorted(
                    mine, key=lambda s: (s["state"] != "NonCompliant", s["definitionName"])
                )[:200]
            ],
        },
        "history": [
            {
                "snapshotAt": _utc(at).isoformat(),
                "family": fam,
                "evidenceQuality": st.evidence_quality,
                "reportedState": st.reported_state,
                "green": st.green,
            }
            for at, fam, st in reversed(hist)
        ],
        "historyNote": f"{len(hist)} sample{'s' if len(hist) != 1 else ''} so far.",
        "labels": LABELS,
    }
