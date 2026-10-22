"""Security-domain categorization views and review workflow.

Read endpoints are restricted to the viewer's authorized subscriptions before anything is
aggregated. A policy or check counts once per domain; framework family counts are distinct counts
per family and overlap by design (see docs/security-domains.md). Overrides are edited only with
the same Azure-RBAC-anchored gate as other shared configuration (never via app roles); when the
gate is not enabled, use the repo/env fallback (ACD_DOMAIN_OVERRIDES[_FILE]).
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.metrics import Family, _authorized_bundle
from app.api.policy import FilterDep, _estate, _iso, _snapshot_time
from app.arm import ArmClient
from app.auth.deps import ArmAccess, arm_access, can_edit_shared_config, current_principal, get_arm
from app.auth.scope import AuthorizedScopes, authorized_scopes
from app.auth.settings import AuthSettings, get_auth_settings
from app.auth.tokens import Principal
from app.config import Settings, get_settings
from app.database import get_session
from app.db_policy import CategoryOverrideRow
from app.domain.domain_store import recompute_domains
from app.domain.domains import (
    CONFIDENCES,
    configured_domain_overrides,
    domain_label,
    domains_in_family,
    framework_family_label,
    frameworks_for,
    load_taxonomy,
    suggest_domain,
    taxonomy_version,
    valid_domain,
)
from app.metrics import policy, views
from app.metrics.engine import FAMILIES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/domains", tags=["security-domains"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ScopesDep = Annotated[AuthorizedScopes, Depends(authorized_scopes)]
PrincipalDep = Annotated[Principal, Depends(current_principal)]
AuthSettingsDep = Annotated[AuthSettings, Depends(get_auth_settings)]
AccessDep = Annotated[ArmAccess, Depends(arm_access)]
ArmDep = Annotated[ArmClient, Depends(get_arm)]

MAX_OVERRIDES = 500
QUEUE_DEFAULT = ("unmapped", "derived-low")
LABELS = [
    "A domain is an app-curated grouping (taxonomy v{v}); it is not a benchmark or certification "
    "mapping. Every item shows where its domain came from and how much to trust it.",
    "A policy or check counts once per domain. Policy compliance % (evaluations) and machine "
    "check pass rate (check results) have different grains and are never combined.",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _pct(n: int, d: int) -> float | None:
    return policy.pct(n, d)


def _mix(counts: dict[str, int]) -> dict[str, Any]:
    total = sum(counts.values())
    return {
        "total": total,
        "byConfidence": {c: counts.get(c, 0) for c in CONFIDENCES},
        "unmapped": counts.get("unmapped", 0),
        "unmappedPercent": _pct(counts.get("unmapped", 0), total),
        "sourcePercent": _pct(counts.get("source", 0), total),
        "derivedPercent": _pct(counts.get("derived-high", 0) + counts.get("derived-low", 0), total),
        "overridePercent": _pct(counts.get("override", 0), total),
    }


def _policy_definitions(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in states:
        d = out.setdefault(
            s["definition"],
            {
                "key": s["definition"],
                "name": s["definitionName"],
                "category": None if s["category"] == policy.UNCATEGORIZED else s["category"],
                "domain": s["domain"],
                "domainSource": s["domainSource"],
                "domainConfidence": s["domainConfidence"],
                "evaluations": 0,
                "nonCompliant": 0,
            },
        )
        d["evaluations"] += 1
        d["nonCompliant"] += s["state"] == "NonCompliant"
    return out


def _check_items(
    session: Session, scopes: AuthorizedScopes, settings: Settings
) -> tuple[datetime | None, list[dict[str, Any]]]:
    found = _authorized_bundle(session, scopes, settings)
    if found is None:
        return None, []
    snap, bundle, stale_after = found
    at = (
        snap.snapshot_at.replace(tzinfo=UTC)
        if snap.snapshot_at.tzinfo is None
        else snap.snapshot_at
    )
    items: list[dict[str, Any]] = []
    for family in FAMILIES:
        items.extend(views.check_inventory(bundle, family, at, stale_after))
    return at, items


@router.get("/taxonomy")
def taxonomy(_: PrincipalDep) -> dict[str, Any]:
    t = load_taxonomy()
    return {
        "taxonomyVersion": t.version,
        "domains": [
            {
                "id": d,
                "label": label,
                "frameworks": {
                    fw: [{"id": f, "label": framework_family_label(fw, f)} for f in fams]
                    for fw, fams in frameworks_for(d).items()
                },
            }
            for d, label in t.labels.items()
        ],
        "frameworks": {
            k: {"label": v["label"], "kind": v["kind"]} for k, v in t.frameworks.items()
        },
        "confidence": {
            "override": "Decided by a reviewer or a repo-managed override.",
            "source": "The definition's / report's own category, mapped through the curated table.",
            "derived-high": "App rule on a section number or a curated check category.",
            "derived-low": "Keyword heuristic on the display name; review recommended.",
            "unmapped": "Nothing matched; the item is in 'Other' and in the review queue.",
        },
        "disclaimer": t.disclaimer,
        "labels": [x.format(v=t.version) for x in LABELS],
    }


@router.get("/overview")
def overview(
    session: SessionDep, settings: SettingsDep, scopes: ScopesDep, flt: FilterDep
) -> dict[str, Any]:
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    by_domain = {r["key"]: r for r in policy.breakdown(states, "domain")}
    at, items = _check_items(session, scopes, settings)
    found = _authorized_bundle(session, scopes, settings)
    machine: dict[str, dict[str, Any]] = defaultdict(dict)
    if found is not None:
        snap, bundle, stale_after = found
        when = (
            snap.snapshot_at.replace(tzinfo=UTC)
            if snap.snapshot_at.tzinfo is None
            else snap.snapshot_at
        )
        for family in FAMILIES:
            for d, tally in views.domain_tallies(bundle, family, when, stale_after).items():
                machine[d][family] = tally
    rows = []
    for d, label in load_taxonomy().labels.items():
        p = by_domain.get(d)
        rows.append(
            {
                "domain": d,
                "label": label,
                "policy": p,
                "machine": machine.get(d, {}),
                "frameworks": frameworks_for(d),
            }
        )
    definitions = _policy_definitions(states)
    pol_mix: dict[str, int] = defaultdict(int)
    for definition in definitions.values():
        pol_mix[definition["domainConfidence"]] += 1
    chk_mix: dict[str, int] = defaultdict(int)
    for c in items:
        chk_mix[c["domainConfidence"]] += 1
    return {
        "taxonomyVersion": taxonomy_version(),
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
        "machineSnapshotAt": _iso(at),
        "domains": rows,
        "provenance": {"policies": _mix(pol_mix), "checks": _mix(chk_mix)},
        "grain": {
            "policy": "policy evaluation; percent = compliant / (compliant + nonCompliant)",
            "machine": "check result on one machine; percent = passed / results (fresh reports)",
        },
        "disclaimer": load_taxonomy().disclaimer,
        "filters": flt.active,
        "labels": [x.format(v=taxonomy_version()) for x in LABELS],
    }


@router.get("/frameworks")
def frameworks(
    session: SessionDep, settings: SettingsDep, scopes: ScopesDep, flt: FilterDep
) -> dict[str, Any]:
    t = load_taxonomy()
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    _, items = _check_items(session, scopes, settings)
    out = []
    for fw_id, fw in t.frameworks.items():
        fams = []
        for fam_id, label in fw["families"].items():
            doms = set(domains_in_family(fw_id, fam_id))
            if not doms:
                continue
            sel = [s for s in states if s["domain"] in doms]
            checks = [c for c in items if c["domain"] in doms]
            tally = policy.tally(sel)
            fams.append(
                {
                    "family": fam_id,
                    "label": label,
                    "domains": sorted(doms),
                    "policies": len({s["definition"] for s in sel}),
                    "evaluations": tally["evaluations"],
                    "compliant": tally["compliant"],
                    "nonCompliant": tally["nonCompliant"],
                    "percent": tally["percent"],
                    "checks": len({(c["family"], c["checkKey"]) for c in checks}),
                    "checksFailing": sum(1 for c in checks if c["machinesFailed"] > 0),
                }
            )
        out.append({"framework": fw_id, "label": fw["label"], "kind": fw["kind"], "families": fams})
    return {
        "taxonomyVersion": t.version,
        "frameworks": out,
        "additive": False,
        "note": "Distinct counts per family. A domain can relate to several families, so family "
        "rows overlap and must not be summed. Indicative related controls, not compliance claims.",
        "disclaimer": t.disclaimer,
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
    }


@router.get("/provenance")
def provenance(
    session: SessionDep, settings: SettingsDep, scopes: ScopesDep, flt: FilterDep
) -> dict[str, Any]:
    data, _ = _estate(session, scopes)
    states = policy.apply_filter(data.states, flt, _now())
    definitions = _policy_definitions(states)
    pol: dict[str, int] = defaultdict(int)
    for d in definitions.values():
        pol[d["domainConfidence"]] += 1
    _, items = _check_items(session, scopes, settings)
    chk: dict[str, int] = defaultdict(int)
    for c in items:
        chk[c["domainConfidence"]] += 1
    return {
        "taxonomyVersion": taxonomy_version(),
        "policies": _mix(pol),
        "checks": _mix(chk),
        "grain": "distinct policy definitions with evaluations in scope; distinct checks",
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
    }


@router.get("/queue")
def queue(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    flt: FilterDep,
    kind: Literal["all", "policy", "check"] = "all",
    confidence: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    wanted = {c for c in (confidence or QUEUE_DEFAULT) if c in CONFIDENCES}
    rows: list[dict[str, Any]] = []
    summary = {"policy": 0, "check": 0}
    if kind in ("all", "policy"):
        data, _ = _estate(session, scopes)
        for d in _policy_definitions(policy.apply_filter(data.states, flt, _now())).values():
            if d["domainConfidence"] in wanted:
                summary["policy"] += 1
                rows.append({"kind": "policy", "family": None, **d})
    if kind in ("all", "check"):
        _, items = _check_items(session, scopes, settings)
        for c in items:
            if c["domainConfidence"] in wanted:
                summary["check"] += 1
                rows.append(
                    {
                        "kind": "check",
                        "key": c["checkKey"],
                        "name": c["name"],
                        "family": c["family"],
                        "category": c["category"],
                        "domain": c["domain"],
                        "domainSource": c["domainSource"],
                        "domainConfidence": c["domainConfidence"],
                        "evaluations": c["machinesPassed"] + c["machinesFailed"],
                        "nonCompliant": c["machinesFailed"],
                    }
                )
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in f"{r['name']} {r['key']}".lower()]
    rows.sort(key=lambda r: (r["domainConfidence"] != "unmapped", -r["evaluations"], r["name"]))
    page = rows[offset : offset + limit]
    for r in page:
        r["suggestedDomain"] = (
            suggest_domain(r["name"]) if r["domainConfidence"] != "source" else None
        )
        r["domainLabel"] = domain_label(r["domain"])
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "summary": summary,
        "confidences": sorted(wanted),
        "rows": page,
        "taxonomyVersion": taxonomy_version(),
        "snapshotAt": _iso(_snapshot_time(session, scopes)),
    }


@router.get("/checks")
def domain_checks(
    session: SessionDep,
    settings: SettingsDep,
    scopes: ScopesDep,
    domain: str,
    family: Family | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if not valid_domain(domain):
        raise HTTPException(422, "Unknown domain")
    _, items = _check_items(session, scopes, settings)
    rows = [c for c in items if c["domain"] == domain and (family is None or c["family"] == family)]
    rows.sort(key=lambda c: (-c["machinesFailed"], c["name"]))
    return {
        "domain": domain,
        "domainLabel": domain_label(domain),
        "total": len(rows),
        "rows": rows[offset : offset + limit],
        "grain": "distinct check; machinesFailed / machinesPassed are machines with a fresh report",
        "taxonomyVersion": taxonomy_version(),
    }


class OverrideRow(BaseModel):
    id: int
    target: str
    kind: str
    pattern: str
    domain: str
    note: str | None
    created_by: str = Field(serialization_alias="createdBy")
    created_at: str = Field(serialization_alias="createdAt")


def _row(r: CategoryOverrideRow) -> dict[str, Any]:
    return OverrideRow(
        id=r.id,
        target=r.target,
        kind=r.kind,
        pattern=r.pattern,
        domain=r.domain,
        note=r.note,
        created_by=r.created_by,
        created_at=r.created_at.isoformat(),
    ).model_dump(by_alias=True)


@router.get("/overrides")
def list_overrides(session: SessionDep, _: PrincipalDep, s: AuthSettingsDep) -> dict[str, Any]:
    rows = session.scalars(select(CategoryOverrideRow).order_by(CategoryOverrideRow.id)).all()
    return {
        "overrides": [_row(r) for r in rows],
        "repoOverrides": len(configured_domain_overrides()),
        "gateEnabled": s.anchor_configured,
        "editing": (
            "Overrides are created by users with Azure deployments/write on the configuration "
            "anchor resource group (the same gate as other shared configuration)."
            if s.anchor_configured
            else "The shared-configuration gate is not enabled in this deployment, so overrides "
            "cannot be edited here. Use ACD_DOMAIN_OVERRIDES / ACD_DOMAIN_OVERRIDES_FILE."
        ),
        "taxonomyVersion": taxonomy_version(),
    }


class OverrideRequest(BaseModel):
    target: Literal["policy", "check"]
    pattern: str = Field(min_length=1, max_length=500)
    domain: str
    note: str | None = Field(default=None, max_length=300)


def _require_edit(access: AccessDep, arm: ArmDep, s: AuthSettingsDep) -> ArmAccess:
    ok, reason = can_edit_shared_config(access, arm, s)
    if not ok:
        raise HTTPException(403, f"Shared configuration editing is not permitted ({reason})")
    return access


@router.post("/overrides", status_code=201)
def create_override(
    body: OverrideRequest,
    session: SessionDep,
    access: AccessDep,
    arm: ArmDep,
    s: AuthSettingsDep,
) -> dict[str, Any]:
    _require_edit(access, arm, s)
    if not valid_domain(body.domain):
        raise HTTPException(422, "Unknown domain")
    pattern = body.pattern.strip().lower() if body.target == "policy" else body.pattern.strip()
    total = len(session.scalars(select(CategoryOverrideRow.id)).all())
    if total >= MAX_OVERRIDES:
        raise HTTPException(409, "Override limit reached")
    existing = session.scalars(
        select(CategoryOverrideRow).where(
            CategoryOverrideRow.target == body.target,
            CategoryOverrideRow.kind == "exact",
            CategoryOverrideRow.pattern == pattern,
        )
    ).first()
    row = existing or CategoryOverrideRow(
        target=body.target,
        kind="exact",
        pattern=pattern,
        created_by=access.principal.object_id,
        created_at=_now(),
    )
    row.domain, row.note = body.domain, body.note
    if existing is None:
        session.add(row)
    session.flush()
    stamped = recompute_domains(session, force=True)
    session.commit()
    log.info(
        "domain override saved",
        extra={"target": body.target, "domain": body.domain, "by": access.principal.object_id},
    )
    return {**_row(row), "recomputed": stamped}


@router.delete("/overrides/{override_id}", status_code=204)
def delete_override(
    override_id: int,
    session: SessionDep,
    access: AccessDep,
    arm: ArmDep,
    s: AuthSettingsDep,
) -> None:
    _require_edit(access, arm, s)
    row = session.get(CategoryOverrideRow, override_id)
    if row is None:
        raise HTTPException(404, "Override not found")
    session.delete(row)
    session.flush()
    recompute_domains(session, force=True)
    session.commit()
    log.info("domain override removed", extra={"by": access.principal.object_id})
