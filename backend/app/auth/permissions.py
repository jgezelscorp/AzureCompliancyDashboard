"""Authorization decisions from Microsoft.Authorization/permissions (fail closed)."""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.arm import ArmClient, ArmError

PERMISSIONS_API_VERSION = "2022-04-01"
SUBSCRIPTIONS_API_VERSION = "2022-12-01"

# Capability mapping: shared configuration editing == deployments/write at the anchor RG.
CONFIG_EDIT_ACTION = "Microsoft.Resources/deployments/write"

# Read actions a viewer needs on a subscription for it to count as readable.
# Every name here must appear in contracts/permissions-manifest.json (tested).
VIEWER_READ_ACTIONS: tuple[str, ...] = (
    "Microsoft.Authorization/policyAssignments/read",
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.HybridCompute/machines/read",
    "Microsoft.GuestConfiguration/guestConfigurationAssignments/read",
)

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_RG = re.compile(r"^[\w.()-]{1,90}$")


class PermissionError_(Exception):
    """Permission data was unusable (treated as deny by callers)."""


def _pattern(action: str) -> re.Pattern[str]:
    return re.compile("^" + ".*".join(re.escape(p) for p in action.split("*")) + "$", re.I)


def _matches(patterns: list[str], action: str) -> bool:
    return any(_pattern(p).match(action) for p in patterns)


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise PermissionError_("unsupported permissions shape")
    return value


def is_action_allowed(pages: list[dict[str, Any]], action: str) -> bool:
    """Azure semantics: allowed if some permission entry has a matching action and no
    matching notAction. dataActions are never consulted. Unsupported shapes raise."""
    if not pages:
        raise PermissionError_("no permission pages")
    allowed = False
    for page in pages:
        entries = page.get("value")
        if not isinstance(entries, list):
            raise PermissionError_("unsupported permissions shape")
        for entry in entries:
            if not isinstance(entry, dict):
                raise PermissionError_("unsupported permissions shape")
            actions = _str_list(entry.get("actions", []))
            not_actions = _str_list(entry.get("notActions", []))
            if _matches(actions, action) and not _matches(not_actions, action):
                allowed = True
    return allowed


def _scope_path(subscription_id: str, resource_group: str | None) -> str:
    if not _GUID.match(subscription_id):
        raise PermissionError_("invalid subscription id")
    path = f"/subscriptions/{subscription_id}"
    if resource_group is not None:
        if not _RG.match(resource_group):
            raise PermissionError_("invalid resource group")
        path += f"/resourcegroups/{quote(resource_group)}"
    return path + "/providers/Microsoft.Authorization/permissions"


def has_action(
    arm: ArmClient,
    arm_token: str,
    subscription_id: str,
    resource_group: str | None,
    action: str,
) -> bool:
    """True only on a positive, complete, well-formed answer. Everything else is False."""
    try:
        pages = arm.get_all(
            _scope_path(subscription_id, resource_group), arm_token, PERMISSIONS_API_VERSION
        )
        return is_action_allowed(pages, action)
    except (ArmError, PermissionError_):
        return False


@dataclass(frozen=True)
class ScopeAccess:
    subscription_id: str
    display_name: str | None
    readable: bool
    missing_actions: tuple[str, ...]


def list_visible_subscriptions(arm: ArmClient, arm_token: str) -> list[tuple[str, str | None]]:
    pages = arm.get_all("/subscriptions", arm_token, SUBSCRIPTIONS_API_VERSION)
    found: list[tuple[str, str | None]] = []
    for page in pages:
        items = page.get("value")
        if not isinstance(items, list):
            raise PermissionError_("unsupported subscriptions shape")
        for item in items:
            sid = item.get("subscriptionId") if isinstance(item, dict) else None
            if not isinstance(sid, str) or not _GUID.match(sid):
                continue
            name = item.get("displayName")
            found.append((sid.lower(), name if isinstance(name, str) else None))
    return found


def assess_subscription(
    arm: ArmClient, arm_token: str, subscription_id: str, display_name: str | None
) -> ScopeAccess:
    missing = tuple(
        a for a in VIEWER_READ_ACTIONS if not has_action(arm, arm_token, subscription_id, None, a)
    )
    return ScopeAccess(subscription_id, display_name, not missing, missing)
