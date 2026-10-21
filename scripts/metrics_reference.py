"""Reference implementation of the contract metrics (docs/metrics-spec.md).

Python and KQL implementations must match this behavior on the golden fixtures.
"""
from datetime import datetime, timedelta, timezone

STALE_AFTER = timedelta(hours=24)


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _ratio(num, den):
    return None if den == 0 else round(100.0 * num / den, 2)


def latest_report(bundle, machine_id, family):
    candidates = [
        r for r in bundle["reports"]
        if r["machineId"] == machine_id and r["baselineFamily"] == family
    ]
    return max(candidates, key=lambda r: r["endTime"], default=None)


def machine_evidence(bundle, machine, family):
    """Return (quality, report) for one machine and baseline family."""
    if machine["eligibility"] == "Unknown":
        return "UnknownApplicability", None
    assigned = [
        a for a in bundle["assignments"]
        if a["machineId"] == machine["machineId"] and a["baselineFamily"] == family
    ]
    if not assigned:
        return "MissingAssignment", None
    report = latest_report(bundle, machine["machineId"], family)
    if report is None:
        return "NoReport", None
    end = parse_ts(report.get("endTime"))
    if end is None:
        return "UnknownAge", report
    age = parse_ts(bundle["snapshotAt"]) - end
    return ("Fresh" if age <= STALE_AFTER else "Stale"), report


def policy_compliance(bundle, family=None):
    states = [
        s for s in bundle["policyStates"]
        if family is None or s.get("baselineFamily") == family
    ]
    compliant = sum(s["complianceState"] == "Compliant" for s in states)
    noncompliant = sum(s["complianceState"] == "NonCompliant" for s in states)
    return {
        "compliant": compliant,
        "nonCompliant": noncompliant,
        "exempt": sum(s["complianceState"] == "Exempt" for s in states),
        "other": len(states) - compliant - noncompliant
        - sum(s["complianceState"] == "Exempt" for s in states),
        "percent": _ratio(compliant, compliant + noncompliant),
    }


def check_pass_rate(bundle, family):
    """Unique checks from the latest FRESH report per machine; reasons are not counted."""
    passed = total = 0
    stale_excluded = 0
    for m in bundle["machines"]:
        quality, report = machine_evidence(bundle, m, family)
        if report is None:
            continue
        if quality != "Fresh":
            stale_excluded += 1
            continue
        keys = {}
        for c in report["checks"]:
            keys[c["checkKey"]] = c["complianceStatus"]
        total += len(keys)
        passed += sum(v == "Compliant" for v in keys.values())
    return {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "percent": _ratio(passed, total),
        "reportsExcludedAsNotFresh": stale_excluded,
    }


def coverage(bundle, family):
    eligible = [m for m in bundle["machines"] if m["eligibility"] == "Eligible"]
    unknown = sum(m["eligibility"] == "Unknown" for m in bundle["machines"])
    quality = {m["machineId"]: machine_evidence(bundle, m, family)[0] for m in eligible}
    assigned = sum(q not in ("MissingAssignment",) for q in quality.values())
    usable = sum(q in ("Fresh", "Stale", "UnknownAge") for q in quality.values())
    fresh = sum(q == "Fresh" for q in quality.values())
    n = len(eligible)
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


def machine_status(bundle, machine, family):
    """Green only when evidence is Fresh AND reported state is Compliant."""
    quality, report = machine_evidence(bundle, machine, family)
    state = report["complianceStatus"] if report else None
    return {
        "machineId": machine["machineId"],
        "evidenceQuality": quality,
        "reportedState": state,
        "green": quality == "Fresh" and state == "Compliant",
    }


def compute(bundle, family):
    return {
        "family": family,
        "policyCompliance": policy_compliance(bundle, family),
        "checkPassRate": check_pass_rate(bundle, family),
        "coverage": coverage(bundle, family),
        "machines": [machine_status(bundle, m, family) for m in bundle["machines"]],
    }
