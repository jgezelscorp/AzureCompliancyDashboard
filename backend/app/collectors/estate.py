"""Estate-wide Azure Policy collection: normalization and idempotent persistence (read-only)."""

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.azure.client import ArmClient, ArmError, PagingError
from app.collectors import sources
from app.collectors.normalize import norm_id, parse_ts
from app.db_policy import (
    DefenderSnapshotRow,
    EstateResourceRow,
    PolicyAssignmentRow,
    PolicyDefinitionRow,
    PolicyExemptionRow,
    PolicyInitiativeRow,
)

DEFAULT_TAG_KEYS = ("owner", "environment", "criticality", "costcenter", "businessunit")
DEFINITION_REFRESH = timedelta(days=7)
UNRESOLVED_RETRY = timedelta(hours=12)
MAX_DEFINITION_LOOKUPS = 600
_SECRET_NAME = re.compile(r"secret|password|pwd|passphrase|token|credential|connection|key", re.I)
_PLACEHOLDER = {"", "tbd", "none", "null"}


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _real(value: Any) -> str | None:
    text = _str(value)
    return None if text is None or text.lower() in _PLACEHOLDER else text


def sub_of(resource_id: str) -> str | None:
    parts = resource_id.lower().split("/")
    return parts[2] if len(parts) > 2 and parts[1] == "subscriptions" else None


def state_extras(raw: dict[str, Any]) -> dict[str, Any]:
    """Attributes of a Policy Insights state row that the contract model does not carry."""
    groups = raw.get("policyDefinitionGroupNames")
    set_id = _real(raw.get("policySetDefinitionId"))
    set_name = _real(raw.get("policySetDefinitionName"))
    action = _real(raw.get("policyDefinitionAction"))
    return {
        "resource_type": _real(raw.get("resourceType")),
        "resource_group": (_real(raw.get("resourceGroup")) or "").lower() or None,
        "location": (_real(raw.get("resourceLocation")) or "").lower() or None,
        "assignment_name": _real(raw.get("policyAssignmentName")),
        "definition_name": _real(raw.get("policyDefinitionName")),
        "initiative_id": norm_id(set_id) if set_id else None,
        "initiative_name": set_name,
        "state_category": _real(raw.get("policyDefinitionCategory")),
        "effect": action.lower() if action else None,
        "group_names": [str(g) for g in groups][:20] if isinstance(groups, list) else None,
    }


def sanitize_parameters(params: Any) -> dict[str, object] | None:
    if not isinstance(params, dict):
        return None
    out: dict[str, object] = {}
    for name, entry in list(params.items())[:30]:
        value = entry.get("value") if isinstance(entry, dict) else entry
        if _SECRET_NAME.search(str(name)):
            out[str(name)] = "[redacted]"
        elif isinstance(value, bool | int | float):
            out[str(name)] = value
        elif isinstance(value, str):
            out[str(name)] = value[:120]
        elif isinstance(value, list):
            out[str(name)] = f"[{len(value)} items]"
        else:
            out[str(name)] = "[object]"
    return out


def normalize_assignment_meta(raw: dict[str, Any]) -> dict[str, Any] | None:
    assignment_id, props = _str(raw.get("id")), raw.get("properties")
    if not assignment_id or not isinstance(props, dict):
        return None
    sub = sub_of(assignment_id) or sub_of(_str(props.get("scope")) or "")
    definition = _str(props.get("policyDefinitionId"))
    if not sub or not definition:
        return None
    not_scopes = props.get("notScopes")
    return {
        "assignment_id": norm_id(assignment_id),
        "subscription_id": sub,
        "name": _str(raw.get("name")) or assignment_id.rsplit("/", 1)[-1],
        "display_name": _str(props.get("displayName")),
        "scope": _str(props.get("scope")),
        "definition_id": norm_id(definition),
        "is_initiative": "/policysetdefinitions/" in definition.lower(),
        "enforcement_mode": _str(props.get("enforcementMode")),
        "not_scopes_count": len(not_scopes) if isinstance(not_scopes, list) else 0,
        "parameters": sanitize_parameters(props.get("parameters")),
    }


def normalize_exemption(raw: dict[str, Any]) -> dict[str, Any] | None:
    exemption_id, props = _str(raw.get("id")), raw.get("properties")
    if not exemption_id or not isinstance(props, dict):
        return None
    sub = sub_of(exemption_id)
    assignment = _str(props.get("policyAssignmentId"))
    if not sub or not assignment:
        return None
    category = str(props.get("exemptionCategory", "")).lower()
    return {
        "exemption_id": norm_id(exemption_id),
        "subscription_id": sub,
        "scope": norm_id(exemption_id.split("/providers/microsoft.authorization/")[0]),
        "assignment_id": norm_id(assignment),
        "display_name": _str(props.get("displayName")),
        "category": {"waiver": "Waiver", "mitigated": "Mitigated"}.get(category),
        "expires_on": parse_ts(props.get("expiresOn")),
    }


def _definition_effect(props: dict[str, Any]) -> str | None:
    effect = ((props.get("policyRule") or {}).get("then") or {}).get("effect")
    if isinstance(effect, str) and effect.startswith("[parameters("):
        name = re.findall(r"parameters\('([^']+)'\)", effect)
        param = (props.get("parameters") or {}).get(name[0]) if name else None
        default = param.get("defaultValue") if isinstance(param, dict) else None
        return str(default).lower() if isinstance(default, str) else None
    return effect.lower() if isinstance(effect, str) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_definition(body: dict[str, Any]) -> dict[str, Any]:
    props = _dict(body.get("properties"))
    meta = _dict(props.get("metadata"))
    severity = _real(meta.get("severity"))
    return {
        "display_name": _str(props.get("displayName")),
        "category": _real(meta.get("category")),
        "severity": severity.capitalize() if severity else None,
        "effect": _definition_effect(props),
        "policy_type": _str(props.get("policyType")),
        "mode": _str(props.get("mode")),
    }


def normalize_initiative(body: dict[str, Any]) -> dict[str, Any]:
    props = _dict(body.get("properties"))
    meta = _dict(props.get("metadata"))
    defs = props.get("policyDefinitions")
    return {
        "display_name": _str(props.get("displayName")),
        "category": _real(meta.get("category")),
        "policy_type": _str(props.get("policyType")),
        "definition_count": len(defs) if isinstance(defs, list) else None,
    }


def normalize_inventory(row: dict[str, Any], tag_keys: Iterable[str]) -> dict[str, Any] | None:
    rid, name, sub = _str(row.get("id")), _str(row.get("name")), _str(row.get("subscriptionId"))
    rtype = _str(row.get("type"))
    if not (rid and name and sub and rtype):
        return None
    wanted = {k.lower() for k in tag_keys}
    tags = row.get("tags")
    kept = (
        {str(k).lower(): str(v)[:120] for k, v in tags.items() if str(k).lower() in wanted}
        if isinstance(tags, dict)
        else {}
    )
    return {
        "resource_id": norm_id(rid),
        "subscription_id": sub.lower(),
        "name": name,
        "resource_type": rtype.lower(),
        "resource_group": (_str(row.get("resourceGroup")) or "").lower() or None,
        "location": (_str(row.get("location")) or "").lower() or None,
        "tags": kept or None,
    }


def normalize_secure_score(items: list[dict[str, Any]]) -> dict[str, object] | None:
    for item in items:
        props = item.get("properties")
        score = props.get("score") if isinstance(props, dict) else None
        if isinstance(score, dict) and isinstance(score.get("max"), int | float):
            current, maximum = score.get("current"), score["max"]
            pct = props.get("percentage") if isinstance(props, dict) else None
            return {
                "current": current,
                "max": maximum,
                "percentage": round(float(pct) * 100, 1) if isinstance(pct, int | float) else None,
            }
    return None


def normalize_standards(items: list[dict[str, Any]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for item in items:
        props = item.get("properties")
        if not isinstance(props, dict):
            continue
        counts = {
            k: int(props.get(k) or 0)
            for k in ("passedControls", "failedControls", "skippedControls", "unsupportedControls")
        }
        out.append(
            {
                "standard": _str(item.get("name")) or "unknown",
                "state": _str(props.get("state")),
                **counts,
            }
        )
    return out


# --- persistence -------------------------------------------------------------------------
def replace_assignments(session: Session, sub: str, rows: list[dict[str, Any]], run_id: int) -> int:
    for r in rows:
        session.merge(PolicyAssignmentRow(**r, run_id=run_id))
    session.flush()
    session.execute(
        delete(PolicyAssignmentRow).where(
            PolicyAssignmentRow.subscription_id == sub,
            or_(PolicyAssignmentRow.run_id != run_id, PolicyAssignmentRow.run_id.is_(None)),
        )
    )
    return len(rows)


def replace_exemptions(session: Session, sub: str, rows: list[dict[str, Any]], run_id: int) -> int:
    for r in rows:
        session.merge(PolicyExemptionRow(**r, run_id=run_id))
    session.flush()
    session.execute(
        delete(PolicyExemptionRow).where(
            PolicyExemptionRow.subscription_id == sub,
            or_(PolicyExemptionRow.run_id != run_id, PolicyExemptionRow.run_id.is_(None)),
        )
    )
    return len(rows)


def replace_inventory(
    session: Session, subs: Iterable[str], rows: list[dict[str, Any]], run_id: int
) -> int:
    for r in rows:
        session.merge(EstateResourceRow(**r, run_id=run_id))
    session.flush()
    session.execute(
        delete(EstateResourceRow).where(
            EstateResourceRow.subscription_id.in_(list(subs)),
            or_(EstateResourceRow.run_id != run_id, EstateResourceRow.run_id.is_(None)),
        )
    )
    return len(rows)


def store_defender(
    session: Session,
    run_id: int,
    at: datetime,
    sub: str,
    available: bool,
    reason: str | None,
    score: dict[str, object] | None,
    standards: list[dict[str, object]] | None,
) -> None:
    session.add(
        DefenderSnapshotRow(
            run_id=run_id,
            snapshot_at=at,
            subscription_id=sub,
            available=available,
            reason=reason,
            secure_score=score,
            standards=standards,
        )
    )


def resolve_metadata(
    session: Session, client: ArmClient, now: datetime, wanted: dict[str, bool]
) -> dict[str, int]:
    """Fetch definition/initiative metadata that is missing or stale; failures are recorded.

    ``wanted`` maps a lower-cased definition id to ``True`` for initiatives. Each lookup is a
    single read-only GET; unresolved ids are retried after a short back-off.
    """
    stats = {"fetched": 0, "failed": 0, "skipped": 0}
    budget = MAX_DEFINITION_LOOKUPS
    for definition_id, is_set in wanted.items():
        row_cls: Any = PolicyInitiativeRow if is_set else PolicyDefinitionRow
        key = row_cls.initiative_id if is_set else row_cls.definition_id
        existing = session.scalars(select(row_cls).where(key == definition_id)).first()
        if existing is not None:
            age = now - existing.refreshed_at.replace(tzinfo=now.tzinfo)
            limit = DEFINITION_REFRESH if existing.resolved else UNRESOLVED_RETRY
            if age < limit:
                stats["skipped"] += 1
                continue
        if budget <= 0:
            stats["skipped"] += 1
            continue
        budget -= 1
        fields: dict[str, Any]
        try:
            body = sources.get_policy_definition(client, definition_id)
            fields = normalize_initiative(body) if is_set else normalize_definition(body)
            resolved = True
            stats["fetched"] += 1
        except (ArmError, PagingError):
            fields, resolved = {}, False
            stats["failed"] += 1
        if existing is None:
            ident = {"initiative_id" if is_set else "definition_id": definition_id}
            existing = row_cls(**ident, refreshed_at=now, resolved=resolved)
            session.add(existing)
        existing.refreshed_at, existing.resolved = now, resolved
        for name, value in fields.items():
            setattr(existing, name, value)
    return stats
