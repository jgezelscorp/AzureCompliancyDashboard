"""Normalize raw ARM / ARG / Policy Insights payloads into the typed evidence contract."""

import re
from datetime import UTC, datetime
from typing import Any

from app.models import Assignment, Check, Machine, PolicyState, Report

AZURE_BASELINE = "AzureWindowsBaseline"
CIS_BASELINE = "CISWindowsSecurityBaseline"
_FRACTION = re.compile(r"(\.\d{6})\d+")
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class NormalizationError(ValueError):
    """A raw item does not have the minimum shape; it is skipped and counted."""


def norm_id(value: str) -> str:
    return value.strip().lower()


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = _FRACTION.sub(r"\1", value.strip().replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def classify_family(guest_configuration_name: str) -> str:
    """Native CIS vs Azure baseline by Machine Configuration name; never merged."""
    name = guest_configuration_name.lower()
    if name == "azurewindowsbaseline":
        return AZURE_BASELINE
    if name == "ciswindowssecuritybaseline" or ("cis" in name and "windows" in name):
        return CIS_BASELINE
    return "Other"


def normalize_state(value: Any) -> str:
    mapping = {"compliant": "Compliant", "noncompliant": "NonCompliant", "pending": "Pending"}
    return mapping.get(str(value).lower(), "Unknown")


def normalize_machine(row: dict[str, Any]) -> Machine:
    machine_id, name = _str(row.get("id")), _str(row.get("name"))
    sub, rg = _str(row.get("subscriptionId")), _str(row.get("resourceGroup"))
    mtype = (_str(row.get("type")) or "").lower()
    if not (machine_id and name and sub and rg) or not _GUID.match(sub):
        raise NormalizationError("machine row is missing id, name, subscription or group")
    if mtype == "microsoft.compute/virtualmachines":
        kind = "AzureVM"
    elif mtype == "microsoft.hybridcompute/machines":
        kind = "ArcMachine"
    else:
        raise NormalizationError(f"unsupported machine type {mtype}")
    os_raw = (_str(row.get("osType")) or "").lower()
    os_type = {"windows": "Windows", "linux": "Linux"}.get(os_raw, "Unknown")
    # Windows machines are eligible for the Windows baseline families; OS evidence missing
    # stays Unknown and is never counted as covered or excluded.
    eligibility = {"Windows": "Eligible", "Linux": "NotEligible"}.get(os_type, "Unknown")
    tags = row.get("tags")
    return Machine.model_validate(
        {
            "machineId": norm_id(machine_id),
            "name": name,
            "kind": kind,
            "subscriptionId": sub.lower(),
            "resourceGroup": rg.lower(),
            "location": _str(row.get("location")),
            "osType": os_type,
            "osName": _str(row.get("osName")),
            "osBuild": _str(row.get("osBuild")),
            "eligibility": eligibility,
            "tags": {str(k): str(v) for k, v in tags.items()} if isinstance(tags, dict) else None,
        }
    )


def normalize_assignment(raw: dict[str, Any], machine_id: str) -> Assignment:
    assignment_id = _str(raw.get("id"))
    props = raw.get("properties")
    if not assignment_id or not isinstance(props, dict):
        raise NormalizationError("assignment is missing id or properties")
    gc = props.get("guestConfiguration")
    gc = gc if isinstance(gc, dict) else {}
    name = _str(gc.get("name")) or _str(raw.get("name"))
    if not name:
        raise NormalizationError("assignment has no guest configuration name")
    return Assignment.model_validate(
        {
            "assignmentId": norm_id(assignment_id),
            "machineId": machine_id,
            "baselineFamily": classify_family(name),
            "guestConfigurationName": name,
            "guestConfigurationVersion": _str(gc.get("version")),
            "assignmentHash": _str(props.get("assignmentHash")),
            "parameterHash": _str(props.get("parameterHash")),
            "contentHash": _str(gc.get("contentHash")),
            "complianceStatus": normalize_state(props.get("complianceStatus")),
            "lastComplianceStatusChecked": parse_ts(props.get("lastComplianceStatusChecked")),
        }
    )


def _check_status(value: Any) -> str:
    if value is True or str(value).lower() in ("true", "compliant"):
        return "Compliant"
    return "NonCompliant"  # false, unknown or malformed is never treated as passing


def _check_key(item: dict[str, Any]) -> str | None:
    """Machine Configuration reports carry the check name in ``properties.ResourceId``."""
    key = _str(item.get("resourceId"))
    if key:
        return key
    props = item.get("properties")
    if isinstance(props, dict):
        for k, v in props.items():
            if k.lower() == "resourceid":
                return _str(v)
    return None


def normalize_checks(details: Any) -> list[Check]:
    """One check per unique resource id; reasons are attached, never counted.

    Duplicate keys keep the worst status so a repeated entry cannot hide a failure.
    """
    resources = details.get("resources") if isinstance(details, dict) else None
    by_key: dict[str, dict[str, Any]] = {}
    for item in resources or []:
        if not isinstance(item, dict):
            continue
        key = _check_key(item)
        if not key:
            continue
        reasons = [
            {
                "phrase": str(r.get("phrase", "")),
                "code": _str(r.get("code")),
                "expected": _str(r.get("expected")),
                "actual": _str(r.get("actual")),
            }
            for r in item.get("reasons") or []
            if isinstance(r, dict)
        ]
        status = _check_status(item.get("complianceStatus"))
        prev = by_key.get(key)
        if prev is not None:
            reasons = prev["reasons"] + reasons
            if prev["complianceStatus"] == "NonCompliant":
                status = "NonCompliant"
        category = re.match(r"^\[([^\]]+)\]", key)
        by_key[key] = {
            "checkKey": key,
            "name": key,
            "complianceStatus": status,
            "category": category.group(1) if category else None,
            "reasons": reasons,
        }
    return [Check.model_validate(c) for c in by_key.values()]


def normalize_report(raw: dict[str, Any], assignment: Assignment) -> Report:
    props = raw.get("properties")
    report_id = _str(raw.get("id"))
    if not isinstance(props, dict) or not report_id:
        raise NormalizationError("report is missing id or properties")
    end = parse_ts(props.get("endTime"))
    start = parse_ts(props.get("startTime")) or end
    if end is None or start is None:
        raise NormalizationError("report has no usable endTime")
    inner = props.get("assignment")
    config = inner.get("configuration") if isinstance(inner, dict) else None
    return Report.model_validate(
        {
            "reportId": norm_id(report_id),
            "assignmentId": assignment.assignment_id,
            "machineId": assignment.machine_id,
            "baselineFamily": assignment.baseline_family,
            "complianceStatus": normalize_state(props.get("complianceStatus")),
            "startTime": start,
            "endTime": end,
            "operationType": _str(props.get("operationType")),
            "configurationVersion": _str(config.get("version"))
            if isinstance(config, dict)
            else None,
            "checks": [c.model_dump(by_alias=True) for c in normalize_checks(props.get("details"))],
        }
    )


class FamilyClassifier:
    """Maps policy definition ids to baseline families via explicit configuration only."""

    def __init__(self, definition_map: dict[str, str]) -> None:
        self._map = {k.lower(): v for k, v in definition_map.items()}

    def classify(self, definition_id: str) -> str:
        d = definition_id.lower()
        if d in self._map:
            return self._map[d]
        return self._map.get(d.rsplit("/", 1)[-1], "Unknown")


_POLICY_STATES = {
    "compliant": "Compliant",
    "noncompliant": "NonCompliant",
    "exempt": "Exempt",
    "conflict": "Conflict",
    "notstarted": "NotStarted",
}


def normalize_policy_state(raw: dict[str, Any], classifier: FamilyClassifier) -> PolicyState:
    resource = _str(raw.get("resourceId"))
    assignment = _str(raw.get("policyAssignmentId"))
    definition = _str(raw.get("policyDefinitionId"))
    ts = parse_ts(raw.get("timestamp"))
    if not (resource and assignment and definition and ts):
        raise NormalizationError("policy state is missing required fields")
    compliant = raw.get("isCompliant")
    return PolicyState.model_validate(
        {
            "resourceId": norm_id(resource),
            "policyAssignmentId": assignment,
            "policyDefinitionId": definition,
            "policyDefinitionReferenceId": _str(raw.get("policyDefinitionReferenceId")),
            "baselineFamily": classifier.classify(definition),
            "complianceState": _POLICY_STATES.get(
                str(raw.get("complianceState")).lower(), "Unknown"
            ),
            "isCompliant": compliant if isinstance(compliant, bool) else None,
            "timestamp": ts,
        }
    )
