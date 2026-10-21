"""Read-only source collectors: Resource Graph, Machine Configuration, Policy Insights."""

from dataclasses import dataclass, field
from typing import Any

from app.azure.client import ArmClient

ARG_API = "2024-04-01"
GC_API = "2024-04-05"
PI_API = "2024-10-01"
ARG_PAGE_SIZE = 1000
ARG_SUBSCRIPTION_LIMIT = 1000

MACHINE_QUERY = """resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
| extend osA = tostring(properties.storageProfile.osDisk.osType),
         osB = tostring(properties.osType),
         nameA = tostring(properties.extended.instanceView.osName),
         nameB = tostring(properties.osSku),
         buildA = tostring(properties.extended.instanceView.osVersion),
         buildB = tostring(properties.osVersion)
| project id, name, type, subscriptionId, resourceGroup, location, tags,
          osType = iff(isnotempty(osA), osA, osB),
          osName = iff(isnotempty(nameA), nameA, nameB),
          osBuild = iff(isnotempty(buildA), buildA, buildB)
| order by id asc"""

# Unverified server-side filter; kept configurable by callers if the spike changes it.
POLICY_STATE_FILTER = (
    "ResourceType eq 'microsoft.compute/virtualmachines' "
    "or ResourceType eq 'microsoft.hybridcompute/machines'"
)


@dataclass
class ArgResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    pages: int = 0


def query_resource_graph(
    client: ArmClient, query: str, subscriptions: list[str], page_size: int = ARG_PAGE_SIZE
) -> ArgResult:
    """Replays the identical query/scope with $skipToken until exhausted.

    A truncated result that cannot be continued is flagged, never reported as complete.
    """
    result = ArgResult()
    for i in range(0, len(subscriptions), ARG_SUBSCRIPTION_LIMIT):
        scope = subscriptions[i : i + ARG_SUBSCRIPTION_LIMIT]
        token: str | None = None
        while True:
            options: dict[str, Any] = {"$top": page_size, "resultFormat": "objectArray"}
            if token:
                options["$skipToken"] = token
            _, page = client.request(
                "POST",
                "/providers/Microsoft.ResourceGraph/resources",
                ARG_API,
                body={"query": query, "subscriptions": scope, "options": options},
            )
            data = page.get("data")
            if not isinstance(data, list):
                result.truncated = True
                break
            result.rows.extend(r for r in data if isinstance(r, dict))
            result.pages += 1
            token = page.get("$skipToken") or None
            if not token:
                if str(page.get("resultTruncated", "false")).lower() == "true":
                    result.truncated = True
                break
    return result


def list_assignments(client: ArmClient, machine_id: str) -> list[dict[str, Any]]:
    path = f"{machine_id}/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments"
    return [v for p in client.get_pages(path, GC_API) for v in _values(p)]


def list_reports(client: ArmClient, assignment_id: str) -> list[dict[str, Any]]:
    return [v for p in client.get_pages(f"{assignment_id}/reports", GC_API) for v in _values(p)]


def get_report(client: ArmClient, report_id: str) -> dict[str, Any]:
    _, body = client.request("GET", report_id, GC_API)
    return body


def query_policy_states(
    client: ArmClient, subscription_id: str, state_filter: str = POLICY_STATE_FILTER
) -> list[dict[str, Any]]:
    path = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.PolicyInsights"
        "/policyStates/latest/queryResults"
    )
    params = {"$top": "1000", "$filter": state_filter}
    return [v for p in client.post_pages(path, PI_API, params=params) for v in _values(p)]


def summarize_policy(client: ArmClient, subscription_id: str) -> dict[str, Any]:
    path = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.PolicyInsights"
        "/policyStates/latest/summarize"
    )
    _, body = client.request("POST", path, PI_API)
    value = body.get("value")
    first = value[0] if isinstance(value, list) and value else {}
    results = first.get("results", {}) if isinstance(first, dict) else {}
    return {
        "nonCompliantResources": results.get("nonCompliantResources"),
        "nonCompliantPolicies": results.get("nonCompliantPolicies"),
    }


def _values(page: dict[str, Any]) -> list[dict[str, Any]]:
    value = page.get("value")
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
