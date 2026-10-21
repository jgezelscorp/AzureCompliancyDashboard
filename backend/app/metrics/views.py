"""Drill-down views over an (already authorized) evidence bundle.

Counts follow docs/metrics-spec.md: only Fresh reports contribute to check results; machines
with stale, missing or unknown evidence are reported separately and never counted as passing.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from app.metrics.engine import _evidence, _Index, _ratio, compute
from app.models import Check, EvidenceBundle, Machine

UNCATEGORIZED = "Uncategorized"


def _fresh_checks(
    bundle: EvidenceBundle, family: str, at: datetime, stale_after: timedelta
) -> Iterator[tuple[Machine, Check]]:
    idx = _Index(bundle, family)
    for m in bundle.machines:
        quality, report = _evidence(idx, m, at, stale_after)
        if report is None or quality != "Fresh":
            continue
        unique: dict[str, Check] = {}
        for c in report.checks:
            unique[c.check_key] = c
        for c in unique.values():
            yield m, c


def restrict(bundle: EvidenceBundle, subscription_id: str) -> EvidenceBundle:
    ids = {m.machine_id for m in bundle.machines if m.subscription_id.lower() == subscription_id}
    return bundle.model_copy(
        update={
            "machines": [m for m in bundle.machines if m.machine_id in ids],
            "assignments": [a for a in bundle.assignments if a.machine_id in ids],
            "reports": [r for r in bundle.reports if r.machine_id in ids],
            "policy_states": [p for p in bundle.policy_states if p.resource_id in ids],
        }
    )


def scopes(
    bundle: EvidenceBundle, families: tuple[str, ...], at: datetime, stale_after: timedelta
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid in sorted({m.subscription_id.lower() for m in bundle.machines}):
        sub = restrict(bundle, sid)
        fams = []
        for f in families:
            m = compute(sub, f, at, stale_after)
            keys = ("family", "policyCompliance", "checkPassRate", "coverage")
            fams.append({k: m[k] for k in keys})
        out.append({"subscriptionId": sid, "machineCount": len(sub.machines), "families": fams})
    return out


def categories(
    bundle: EvidenceBundle, family: str, at: datetime, stale_after: timedelta
) -> list[dict[str, Any]]:
    acc: dict[str, list[int]] = {}
    keys: dict[str, set[str]] = {}
    for _, c in _fresh_checks(bundle, family, at, stale_after):
        cat = c.category or UNCATEGORIZED
        a = acc.setdefault(cat, [0, 0])
        a[0] += c.compliance_status == "Compliant"
        a[1] += 1
        keys.setdefault(cat, set()).add(c.check_key)
    return [
        {
            "category": cat,
            "checks": len(keys[cat]),
            "passed": p,
            "total": t,
            "percent": _ratio(p, t),
        }
        for cat, (p, t) in sorted(acc.items())
    ]


def checks(
    bundle: EvidenceBundle, family: str, category: str, at: datetime, stale_after: timedelta
) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}
    for _, c in _fresh_checks(bundle, family, at, stale_after):
        if (c.category or UNCATEGORIZED) != category:
            continue
        row = acc.setdefault(
            c.check_key,
            {
                "checkKey": c.check_key,
                "name": c.name,
                "severity": c.severity,
                "benchmarkControlId": c.benchmark_control_id,
                "machinesPassed": 0,
                "machinesFailed": 0,
            },
        )
        row["machinesPassed" if c.compliance_status == "Compliant" else "machinesFailed"] += 1
    return sorted(acc.values(), key=lambda r: (-r["machinesFailed"], r["checkKey"]))


def check_machines(
    bundle: EvidenceBundle, family: str, check_key: str, at: datetime, stale_after: timedelta
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m, c in _fresh_checks(bundle, family, at, stale_after):
        if c.check_key != check_key:
            continue
        out.append(
            {
                "machineId": m.machine_id,
                "name": m.name,
                "subscriptionId": m.subscription_id.lower(),
                "status": c.compliance_status,
                "reasons": [
                    {"phrase": r.phrase, "expected": r.expected, "actual": r.actual}
                    for r in c.reasons
                ],
            }
        )
    return sorted(out, key=lambda r: (r["status"] == "Compliant", r["name"].lower()))
