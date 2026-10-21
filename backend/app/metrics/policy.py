"""Estate-wide Azure Policy metrics (docs/policy-estate.md).

Pure functions over rows already restricted to the viewer's authorized subscriptions, so
authorization is applied before any aggregation. There is no composite risk score: every number
names its numerator, denominator and grain.

Grains:
- evaluation: one Policy Insights state record (resource x assignment x policy reference);
- resource: one distinct resource id (subscription-scope evaluations count as resources);
- policy: one distinct policy definition.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_history import PolicyStateRow
from app.db_policy import (
    EstateResourceRow,
    PolicyAssignmentRow,
    PolicyDefinitionRow,
    PolicyExemptionRow,
    PolicyInitiativeRow,
)

STANDALONE = "__standalone"
UNCATEGORIZED = "Uncategorized"
UNTAGGED = "(untagged)"
ENFORCEMENT_EFFECTS = frozenset({"deny", "deployifnotexists", "modify", "append"})
HIGH_SEVERITIES = frozenset({"high", "critical"})
COUNTED = ("Compliant", "NonCompliant")
DIMENSIONS = (
    "initiative",
    "assignment",
    "definition",
    "resourceType",
    "subscription",
    "resourceGroup",
    "location",
    "category",
    "effect",
    "severity",
    "state",
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def pct(num: int, den: int) -> float | None:
    return None if den == 0 else round(100.0 * num / den, 2)


def tail(identifier: str) -> str:
    return identifier.rstrip("/").rsplit("/", 1)[-1]


@dataclass
class EstateData:
    states: list[dict[str, Any]] = field(default_factory=list)
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    exemptions: list[dict[str, Any]] = field(default_factory=list)
    assignments: dict[str, dict[str, Any]] = field(default_factory=dict)
    initiatives: dict[str, dict[str, Any]] = field(default_factory=dict)
    definitions: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def severity_metadata_present(self) -> bool:
        return any(d.get("severity") for d in self.definitions.values())


def load_estate(session: Session, subscriptions: frozenset[str]) -> EstateData:
    subs = list(subscriptions)
    data = EstateData()
    if not subs:
        return data
    for d in session.scalars(select(PolicyDefinitionRow)):
        data.definitions[d.definition_id] = {
            "name": d.display_name,
            "category": d.category,
            "severity": (d.severity or "").lower() or None,
            "effect": d.effect,
            "type": d.policy_type,
        }
    for i in session.scalars(select(PolicyInitiativeRow)):
        data.initiatives[i.initiative_id] = {
            "name": i.display_name,
            "category": i.category,
            "type": i.policy_type,
            "definitions": i.definition_count,
        }
    for a in session.scalars(
        select(PolicyAssignmentRow).where(PolicyAssignmentRow.subscription_id.in_(subs))
    ):
        data.assignments[a.assignment_id] = {
            "name": a.display_name or a.name,
            "scope": a.scope,
            "enforcement": a.enforcement_mode,
            "isInitiative": a.is_initiative,
            "notScopes": a.not_scopes_count,
            "parameters": a.parameters,
        }
    for r in session.scalars(
        select(EstateResourceRow).where(EstateResourceRow.subscription_id.in_(subs))
    ):
        data.resources[r.resource_id] = {
            "name": r.name,
            "type": r.resource_type,
            "rg": r.resource_group,
            "loc": r.location,
            "tags": r.tags or {},
        }
    for e in session.scalars(
        select(PolicyExemptionRow).where(PolicyExemptionRow.subscription_id.in_(subs))
    ):
        data.exemptions.append(
            {
                "id": e.exemption_id,
                "sub": e.subscription_id,
                "scope": e.scope,
                "assignment": e.assignment_id,
                "name": e.display_name,
                "category": e.category,
                "expiresOn": utc(e.expires_on) if e.expires_on else None,
            }
        )
    for s in session.scalars(
        select(PolicyStateRow).where(PolicyStateRow.subscription_id.in_(subs))
    ):
        definition = (s.policy_definition_id or "").lower()
        meta = data.definitions.get(definition, {})
        assignment = s.policy_assignment_id.lower()
        initiative = s.initiative_id
        init_meta = data.initiatives.get(initiative or "", {})
        inv = data.resources.get(s.resource_id, {})
        data.states.append(
            {
                "rid": s.resource_id,
                "sub": s.subscription_id.lower(),
                "rg": s.resource_group,
                "loc": s.location,
                "rtype": (s.resource_type or inv.get("type") or "unknown").lower(),
                "assignment": assignment,
                "assignmentName": data.assignments.get(assignment, {}).get("name")
                or s.assignment_name
                or tail(assignment),
                "definition": definition,
                "definitionName": meta.get("name") or s.definition_name or tail(definition),
                "ref": s.reference_id or None,
                "initiative": initiative or STANDALONE,
                "initiativeName": init_meta.get("name")
                or s.initiative_name
                or (tail(initiative) if initiative else "Standalone policy assignments"),
                "state": s.compliance_state,
                "effect": (s.effect or meta.get("effect") or "unknown").lower(),
                "category": meta.get("category") or s.state_category or UNCATEGORIZED,
                "severity": meta.get("severity"),
                "ts": utc(s.state_timestamp),
                "groups": s.group_names or [],
                "resourceName": inv.get("name") or tail(s.resource_id),
                "tags": inv.get("tags") or {},
            }
        )
    return data


# --- filtering ------------------------------------------------------------------------------
@dataclass(frozen=True)
class StateFilter:
    subscription: tuple[str, ...] = ()
    resource_group: tuple[str, ...] = ()
    location: tuple[str, ...] = ()
    resource_type: tuple[str, ...] = ()
    initiative: tuple[str, ...] = ()
    assignment: tuple[str, ...] = ()
    definition: tuple[str, ...] = ()
    state: tuple[str, ...] = ()
    category: tuple[str, ...] = ()
    effect: tuple[str, ...] = ()
    severity: tuple[str, ...] = ()
    tag: tuple[str, ...] = ()  # "key:value"
    max_age_hours: int | None = None
    min_age_hours: int | None = None
    q: str = ""

    @property
    def active(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in ((), None, "")}


def _matches(f: StateFilter, s: dict[str, Any], now: datetime) -> bool:
    checks: tuple[tuple[tuple[str, ...], Any], ...] = (
        (f.subscription, s["sub"]),
        (f.resource_group, s["rg"]),
        (f.location, s["loc"]),
        (f.resource_type, s["rtype"]),
        (f.initiative, s["initiative"]),
        (f.assignment, s["assignment"]),
        (f.definition, s["definition"]),
        (f.state, s["state"]),
        (f.category, s["category"]),
        (f.effect, s["effect"]),
        (f.severity, s["severity"] or "none"),
    )
    for wanted, actual in checks:
        if wanted and str(actual or "").lower() not in {w.lower() for w in wanted}:
            return False
    if f.tag:
        pairs = {f"{k}:{v}".lower() for k, v in s["tags"].items()}
        if not any(t.lower() in pairs for t in f.tag):
            return False
    age = now - s["ts"]
    if f.max_age_hours is not None and age > timedelta(hours=f.max_age_hours):
        return False
    if f.min_age_hours is not None and age <= timedelta(hours=f.min_age_hours):
        return False
    if f.q:
        needle = f.q.lower()
        hay = " ".join(
            str(s[k] or "")
            for k in ("rid", "definitionName", "assignmentName", "initiativeName", "rtype")
        ).lower()
        if needle not in hay:
            return False
    return True


def apply_filter(
    states: list[dict[str, Any]], f: StateFilter, now: datetime
) -> list[dict[str, Any]]:
    if not f.active:
        return states
    return [s for s in states if _matches(f, s, now)]


# --- aggregation ----------------------------------------------------------------------------
def tally(states: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for one group. ``percent`` = Compliant / (Compliant + NonCompliant) evaluations."""
    c = sum(s["state"] == "Compliant" for s in states)
    nc = sum(s["state"] == "NonCompliant" for s in states)
    ex = sum(s["state"] == "Exempt" for s in states)
    resources = {s["rid"] for s in states}
    nc_resources = {s["rid"] for s in states if s["state"] == "NonCompliant"}
    return {
        "evaluations": len(states),
        "compliant": c,
        "nonCompliant": nc,
        "exempt": ex,
        "other": len(states) - c - nc - ex,
        "percent": pct(c, c + nc),
        "resources": len(resources),
        "nonCompliantResources": len(nc_resources),
        "nonCompliantPolicies": len(
            {s["definition"] for s in states if s["state"] == "NonCompliant"}
        ),
    }


def headline(states: list[dict[str, Any]]) -> dict[str, Any]:
    t = tally(states)
    by_resource: dict[str, set[str]] = defaultdict(set)
    for s in states:
        by_resource[s["rid"]].add(s["state"])
    counted = [v for v in by_resource.values() if v & set(COUNTED)]
    fully = sum(1 for v in counted if "NonCompliant" not in v)
    failing = [s for s in states if s["state"] == "NonCompliant"]
    t["resourcesCounted"] = len(counted)
    t["resourcesFullyCompliant"] = fully
    t["resourcePercent"] = pct(fully, len(counted))
    t["highImpactFailingPolicies"] = len(
        {s["definition"] for s in failing if (s["severity"] or "") in HIGH_SEVERITIES}
    )
    t["enforcementFailingPolicies"] = len(
        {s["definition"] for s in failing if s["effect"] in ENFORCEMENT_EFFECTS}
    )
    return t


def _key_label(dim: str, s: dict[str, Any]) -> tuple[str, str]:
    if dim == "initiative":
        return s["initiative"], s["initiativeName"]
    if dim == "assignment":
        return s["assignment"], s["assignmentName"]
    if dim == "definition":
        return s["definition"], s["definitionName"]
    if dim == "resourceType":
        return s["rtype"], s["rtype"]
    if dim == "subscription":
        return s["sub"], s["sub"]
    if dim == "resourceGroup":
        rg = s["rg"] or "(subscription scope)"
        return f"{s['sub']}|{rg}", rg
    if dim == "location":
        return s["loc"] or "(global)", s["loc"] or "(global)"
    if dim == "category":
        return s["category"], s["category"]
    if dim == "effect":
        return s["effect"], s["effect"]
    if dim == "severity":
        sev = s["severity"] or "none"
        return sev, sev if s["severity"] else "No severity metadata"
    if dim == "state":
        return s["state"], s["state"]
    if dim.startswith("tag:"):
        value = s["tags"].get(dim[4:].lower())
        return (value or UNTAGGED), (value or UNTAGGED)
    raise ValueError(f"unknown dimension {dim}")


def valid_dimension(dim: str) -> bool:
    return dim in DIMENSIONS or (dim.startswith("tag:") and 1 < len(dim) < 64)


SORTS = ("nonCompliant", "percent", "evaluations", "resources", "nonCompliantResources", "label")


def breakdown(
    states: list[dict[str, Any]], dim: str, sort: str = "nonCompliant", descending: bool = True
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, str] = {}
    for s in states:
        key, label = _key_label(dim, s)
        groups[key].append(s)
        labels[key] = label
    rows = [{"key": k, "label": labels[k], **tally(v)} for k, v in groups.items()]
    if sort == "label":
        rows.sort(key=lambda r: str(r["label"]).lower(), reverse=descending)
    else:
        # None percent (nothing counted) always sorts last: no data is never "best".
        rows.sort(
            key=lambda r: (
                r[sort] is None,
                -(r[sort] or 0) if descending else (r[sort] or 0),
                r["label"],
            )
        )
    return rows


def top_policies(states: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    failing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in states:
        if s["state"] == "NonCompliant":
            failing[s["definition"]].append(s)
    rows = []
    for definition, items in failing.items():
        first = items[0]
        rows.append(
            {
                "definition": definition,
                "name": first["definitionName"],
                "category": first["category"],
                "effect": first["effect"],
                "severity": first["severity"],
                "nonCompliant": len(items),
                "affectedResources": len({i["rid"] for i in items}),
                "assignments": len({i["assignment"] for i in items}),
                "initiatives": sorted({i["initiativeName"] for i in items})[:5],
            }
        )
    rows.sort(key=lambda r: (-r["affectedResources"], -r["nonCompliant"], r["name"]))
    return rows[:limit]


def resource_rows(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in states:
        groups[s["rid"]].append(s)
    rows = []
    for rid, items in groups.items():
        t = tally(items)
        first = items[0]
        rows.append(
            {
                "resourceId": rid,
                "name": first["resourceName"],
                "resourceType": first["rtype"],
                "subscriptionId": first["sub"],
                "resourceGroup": first["rg"],
                "location": first["loc"],
                "tags": first["tags"],
                "evaluations": t["evaluations"],
                "compliant": t["compliant"],
                "nonCompliant": t["nonCompliant"],
                "exempt": t["exempt"],
                "other": t["other"],
                "failingPolicies": t["nonCompliantPolicies"],
                "newestEvaluation": max(i["ts"] for i in items).isoformat(),
            }
        )
    return rows


def exemption_summary(exemptions: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    buckets = {"active": 0, "noExpiry": 0, "expiring30": 0, "expiring60": 0, "expiring90": 0}
    expired = 0
    items = []
    for e in exemptions:
        exp = e["expiresOn"]
        if exp is None:
            status, days = "active", None
            buckets["active"] += 1
            buckets["noExpiry"] += 1
        elif exp <= now:
            status, days = "expired", int((exp - now).total_seconds() // 86400)
            expired += 1
        else:
            days = int((exp - now).total_seconds() // 86400)
            status = "active"
            buckets["active"] += 1
            for limit in (30, 60, 90):
                if days < limit:
                    buckets[f"expiring{limit}"] += 1
                    break
        items.append(
            {
                "id": e["id"],
                "name": e["name"],
                "scope": e["scope"],
                "assignment": e["assignment"],
                "category": e["category"],
                "expiresOn": exp.isoformat() if exp else None,
                "daysToExpiry": days,
                "status": status,
            }
        )
    items.sort(key=lambda i: (i["expiresOn"] is None, i["expiresOn"] or ""))
    # Buckets are exclusive (<30, 30-59, 60-89 days) so the timeline never double counts.
    return {"buckets": {**buckets, "expired": expired}, "total": len(exemptions), "items": items}


def freshness(states: list[dict[str, Any]], now: datetime, hours: int) -> dict[str, Any]:
    if not states:
        return {"evaluations": 0, "fresh": 0, "percent": None, "newest": None, "oldest": None}
    fresh = sum(now - s["ts"] <= timedelta(hours=hours) for s in states)
    return {
        "evaluations": len(states),
        "fresh": fresh,
        "percent": pct(fresh, len(states)),
        "newest": max(s["ts"] for s in states).isoformat(),
        "oldest": min(s["ts"] for s in states).isoformat(),
        "thresholdHours": hours,
    }


def snapshot_metrics(
    states: list[dict[str, Any]],
    exemptions: list[dict[str, Any]],
    inventory: int,
    now: datetime,
    changes: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compact per-subscription aggregate persisted with every collection run."""
    h = headline(states)
    by_initiative = {
        r["key"]: {
            "label": r["label"],
            "compliant": r["compliant"],
            "nonCompliant": r["nonCompliant"],
            "exempt": r["exempt"],
            "other": r["other"],
        }
        for r in breakdown(states, "initiative")
    }
    ex = exemption_summary(exemptions, now)["buckets"]
    return {
        "headline": {k: h[k] for k in h if k != "percent" and k != "resourcePercent"},
        "byInitiative": by_initiative,
        "exemptions": ex,
        "inventory": inventory,
        "changes": changes or {},
    }


def diff_states(
    old: dict[tuple[str, str, str], str], new: dict[tuple[str, str, str], str]
) -> dict[str, Any]:
    """Regressions/recoveries between two consecutive collections (same grain: evaluation)."""
    regressions = recoveries = appeared_nc = resolved_nc = 0
    movers: list[dict[str, str]] = []
    for key, state in new.items():
        before = old.get(key)
        if before is None:
            if state == "NonCompliant":
                appeared_nc += 1
                movers.append(
                    {
                        "resourceId": key[0],
                        "assignment": key[1],
                        "ref": key[2],
                        "to": state,
                        "from": "new",
                    }
                )
        elif before != state:
            if before == "Compliant" and state == "NonCompliant":
                regressions += 1
            elif before == "NonCompliant" and state == "Compliant":
                recoveries += 1
            if "NonCompliant" in (before, state):
                movers.append(
                    {
                        "resourceId": key[0],
                        "assignment": key[1],
                        "ref": key[2],
                        "from": before,
                        "to": state,
                    }
                )
    for key, before in old.items():
        if key not in new and before == "NonCompliant":
            resolved_nc += 1
    return {
        "regressions": regressions,
        "recoveries": recoveries,
        "newNonCompliant": appeared_nc,
        "noLongerReportedNonCompliant": resolved_nc,
        "movers": movers[:50],
        "comparable": bool(old),
    }
