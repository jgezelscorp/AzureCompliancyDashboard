"""Metrics per docs/metrics-spec.md. Output shape is identical to scripts/metrics_reference.py.

Azure Policy compliance %, check pass rate and coverage are separate and never blended.
Missing or stale data is never green; reasons are not checks.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import EvidenceBundle, Machine, Report

STALE_AFTER = timedelta(hours=24)
FAMILIES = ("AzureWindowsBaseline", "CISWindowsSecurityBaseline")


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(100.0 * num / den, 2)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class _Index:
    def __init__(self, bundle: EvidenceBundle, family: str) -> None:
        self.assigned: set[str] = {
            a.machine_id for a in bundle.assignments if a.baseline_family == family
        }
        self.latest: dict[str, Report] = {}
        for r in bundle.reports:
            if r.baseline_family != family:
                continue
            cur = self.latest.get(r.machine_id)
            if cur is None or _utc(r.end_time) > _utc(cur.end_time):
                self.latest[r.machine_id] = r


def _evidence(
    idx: _Index, machine: Machine, snapshot_at: datetime, stale_after: timedelta
) -> tuple[str, Report | None]:
    if machine.eligibility == "Unknown":
        return "UnknownApplicability", None
    if machine.machine_id not in idx.assigned:
        return "MissingAssignment", None
    report = idx.latest.get(machine.machine_id)
    if report is None:
        return "NoReport", None
    end: datetime | None = report.end_time
    if end is None:
        return "UnknownAge", report
    age = _utc(snapshot_at) - _utc(end)
    return ("Fresh" if age <= stale_after else "Stale"), report


def policy_compliance(bundle: EvidenceBundle, family: str | None = None) -> dict[str, Any]:
    states = [s for s in bundle.policy_states if family is None or s.baseline_family == family]
    compliant = sum(s.compliance_state == "Compliant" for s in states)
    noncompliant = sum(s.compliance_state == "NonCompliant" for s in states)
    exempt = sum(s.compliance_state == "Exempt" for s in states)
    return {
        "compliant": compliant,
        "nonCompliant": noncompliant,
        "exempt": exempt,
        "other": len(states) - compliant - noncompliant - exempt,
        "percent": _ratio(compliant, compliant + noncompliant),
    }


def check_pass_rate(
    bundle: EvidenceBundle, family: str, snapshot_at: datetime, stale_after: timedelta
) -> dict[str, Any]:
    idx = _Index(bundle, family)
    passed = total = excluded = 0
    for m in bundle.machines:
        quality, report = _evidence(idx, m, snapshot_at, stale_after)
        if report is None:
            continue
        if quality != "Fresh":
            excluded += 1
            continue
        keys: dict[str, str] = {}
        for c in report.checks:
            keys[c.check_key] = c.compliance_status
        total += len(keys)
        passed += sum(v == "Compliant" for v in keys.values())
    return {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "percent": _ratio(passed, total),
        "reportsExcludedAsNotFresh": excluded,
    }


def coverage(
    bundle: EvidenceBundle, family: str, snapshot_at: datetime, stale_after: timedelta
) -> dict[str, Any]:
    idx = _Index(bundle, family)
    eligible = [m for m in bundle.machines if m.eligibility == "Eligible"]
    unknown = sum(m.eligibility == "Unknown" for m in bundle.machines)
    quality = [_evidence(idx, m, snapshot_at, stale_after)[0] for m in eligible]
    n = len(eligible)
    assigned = sum(q != "MissingAssignment" for q in quality)
    usable = sum(q in ("Fresh", "Stale", "UnknownAge") for q in quality)
    fresh = sum(q == "Fresh" for q in quality)
    return {
        "eligible": n,
        "unknownEligibility": unknown,
        "assigned": assigned,
        "usableReport": usable,
        "freshReport": fresh,
        "assignmentPercent": _ratio(assigned, n),
        "usableReportPercent": _ratio(usable, n),
        "freshReportPercent": _ratio(fresh, n),
    }


def machine_statuses(
    bundle: EvidenceBundle, family: str, snapshot_at: datetime, stale_after: timedelta
) -> list[dict[str, Any]]:
    """Green only when evidence is Fresh AND reported state is Compliant."""
    idx = _Index(bundle, family)
    out: list[dict[str, Any]] = []
    for m in bundle.machines:
        quality, report = _evidence(idx, m, snapshot_at, stale_after)
        state = report.compliance_status if report else None
        out.append(
            {
                "machineId": m.machine_id,
                "evidenceQuality": quality,
                "reportedState": state,
                "green": quality == "Fresh" and state == "Compliant",
            }
        )
    return out


def compute(
    bundle: EvidenceBundle,
    family: str,
    snapshot_at: datetime | None = None,
    stale_after: timedelta = STALE_AFTER,
) -> dict[str, Any]:
    at = snapshot_at or bundle.snapshot_at
    if at is None:
        raise ValueError("snapshot_at is required")
    return {
        "family": family,
        "policyCompliance": policy_compliance(bundle, family),
        "checkPassRate": check_pass_rate(bundle, family, at, stale_after),
        "coverage": coverage(bundle, family, at, stale_after),
        "machines": machine_statuses(bundle, family, at, stale_after),
    }


def unclassified_policy_states(bundle: EvidenceBundle) -> int:
    return sum(s.baseline_family not in FAMILIES for s in bundle.policy_states)


__all__ = [
    "FAMILIES",
    "STALE_AFTER",
    "check_pass_rate",
    "compute",
    "coverage",
    "machine_statuses",
    "policy_compliance",
    "unclassified_policy_states",
]
