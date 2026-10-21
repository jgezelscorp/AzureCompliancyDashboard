"""Synthetic ARM transport for tests. No network, no live Azure; all data comes from fixtures."""

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.azure.client import ArmRequest, ArmResponse

SUB_RE = re.compile(r"/subscriptions/([0-9a-f-]{36})/", re.I)


def arg_row(m: dict[str, Any]) -> dict[str, Any]:
    kind = "microsoft.compute/virtualmachines"
    if m["kind"] == "ArcMachine":
        kind = "microsoft.hybridcompute/machines"
    return {
        "id": m["machineId"],
        "name": m["name"],
        "type": kind,
        "subscriptionId": m["subscriptionId"],
        "resourceGroup": m["resourceGroup"],
        "location": m.get("location"),
        "osType": "" if m["eligibility"] == "Unknown" else m["osType"],
        "osName": m.get("osName"),
        "osBuild": m.get("osBuild"),
        "tags": m.get("tags"),
    }


def raw_assignment(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["assignmentId"],
        "name": a["guestConfigurationName"],
        "properties": {
            "guestConfiguration": {
                "name": a["guestConfigurationName"],
                "version": a.get("guestConfigurationVersion"),
                "contentHash": a.get("contentHash"),
            },
            "parameterHash": a.get("parameterHash"),
            "complianceStatus": a["complianceStatus"],
            "lastComplianceStatusChecked": a.get("lastComplianceStatusChecked"),
        },
    }


def report_arm_id(r: dict[str, Any]) -> str:
    return f"{r['assignmentId']}/reports/{r['reportId']}"


def raw_report(r: dict[str, Any], with_details: bool) -> dict[str, Any]:
    props: dict[str, Any] = {
        "complianceStatus": r["complianceStatus"],
        "startTime": r["startTime"],
        "endTime": r["endTime"],
        "operationType": r.get("operationType"),
        "assignment": {"configuration": {"version": r.get("configurationVersion")}},
    }
    if with_details:
        props["details"] = {
            "resources": [
                {
                    "properties": {"ResourceId": c["checkKey"], "Message": "truncated"},
                    "complianceStatus": c["complianceStatus"],
                    "reasons": [
                        {"phrase": x["phrase"], "code": x.get("code")} for x in c["reasons"]
                    ],
                }
                for c in r["checks"]
            ]
        }
    return {"id": report_arm_id(r), "name": r["reportId"], "properties": props}


def raw_policy_state(s: dict[str, Any]) -> dict[str, Any]:
    return {
        k: s.get(k)
        for k in (
            "resourceId",
            "policyAssignmentId",
            "policyDefinitionId",
            "policyDefinitionReferenceId",
            "complianceState",
            "isCompliant",
            "timestamp",
            "resourceType",
            "resourceGroup",
            "resourceLocation",
            "policyAssignmentName",
            "policyDefinitionName",
            "policySetDefinitionId",
            "policySetDefinitionName",
            "policyDefinitionAction",
            "policyDefinitionCategory",
            "policyDefinitionGroupNames",
        )
    }


class FakeArm:
    """Serves a fixture bundle through ARM-shaped responses and records every request."""

    def __init__(
        self,
        bundle: dict[str, Any],
        *,
        arg_page_size: int = 1000,
        policy_page_size: int = 1000,
        overrides: Callable[[ArmRequest], ArmResponse | None] | None = None,
    ) -> None:
        self.bundle = bundle
        self.requests: list[ArmRequest] = []
        self.arg_page_size = arg_page_size
        self.policy_page_size = policy_page_size
        self.overrides = overrides

    def send(self, request: ArmRequest) -> ArmResponse:
        self.requests.append(request)
        if self.overrides and (custom := self.overrides(request)):
            return custom
        parts = urlsplit(request.url)
        path = parts.path.lower()
        query = dict(parse_qsl(parts.query))
        if path == "/providers/microsoft.resourcegraph/resources":
            return self._arg(request.json)
        if path.endswith("/policystates/latest/queryresults"):
            return self._policy(path, query)
        if path.endswith("/policystates/latest/summarize"):
            return ArmResponse(200, {}, {"value": [{"results": {"nonCompliantResources": 0}}]})
        if path.endswith("/policyassignments"):
            return ArmResponse(200, {}, {"value": self.bundle.get("policyAssignments", [])})
        if path.endswith("/policyexemptions"):
            return ArmResponse(200, {}, {"value": self.bundle.get("policyExemptions", [])})
        if "/policydefinitions/" in path or "/policysetdefinitions/" in path:
            defs = self.bundle.get("policyDefinitions", {})
            if path.rsplit("/", 1)[-1] in defs:
                return ArmResponse(200, {}, defs[path.rsplit("/", 1)[-1]])
        if path.endswith("/guestconfigurationassignments"):
            machine = path[
                : -len("/providers/microsoft.guestconfiguration/guestconfigurationassignments")
            ]
            vals = [
                raw_assignment(a)
                for a in self.bundle["assignments"]
                if a["machineId"].lower() == machine
            ]
            return ArmResponse(200, {}, {"value": vals})
        if path.endswith("/reports"):
            assignment = path[: -len("/reports")]
            vals = [
                raw_report(r, False)
                for r in self.bundle["reports"]
                if r["assignmentId"].lower() == assignment
            ]
            return ArmResponse(200, {}, {"value": vals})
        if "/reports/" in path:
            for r in self.bundle["reports"]:
                if report_arm_id(r).lower() == path:
                    return ArmResponse(200, {}, raw_report(r, True))
        return ArmResponse(404, {}, {"error": {"code": "NotFound", "message": "synthetic"}})

    def _arg(self, body: Any) -> ArmResponse:
        rows = sorted((arg_row(m) for m in self.bundle["machines"]), key=lambda r: r["id"])
        opts = body["options"]
        start = int(opts.get("$skipToken") or 0)
        size = min(int(opts["$top"]), self.arg_page_size)
        page = rows[start : start + size]
        out: dict[str, Any] = {"count": len(page), "totalRecords": len(rows), "data": page}
        if start + size < len(rows):
            out["$skipToken"] = str(start + size)
        return ArmResponse(200, {}, out)

    def _policy(self, path: str, query: dict[str, str]) -> ArmResponse:
        sub = SUB_RE.search(path)
        assert sub
        states = [
            raw_policy_state(s)
            for s in self.bundle["policyStates"]
            if sub.group(1) in s["resourceId"].lower()
        ]
        start = int(query.get("$skiptoken", 0))
        size = self.policy_page_size
        out: dict[str, Any] = {"value": states[start : start + size]}
        if start + size < len(states):
            out["@odata.nextLink"] = (
                f"https://management.azure.com{path}"
                f"?api-version=2024-10-01&$skiptoken={start + size}"
            )
        return ArmResponse(200, {}, out)


def load_json(path: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data
