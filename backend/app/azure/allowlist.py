"""Method + host + path template + api-version allowlist (mirrors contracts/source-manifest.json).

Default action is deny. A GET-only rule is not enough: POST is allowed only for the three
read-only query operations flagged ``read_only_query_post``.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

PERMITTED_HOST = "management.azure.com"
_GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SEG = r"[^/]+"
_MACHINE = (
    rf"/subscriptions/{_GUID}/resourcegroups/{_SEG}/providers/"
    rf"(?:microsoft\.compute/virtualmachines|microsoft\.hybridcompute/machines)/{_SEG}"
)
_GC = "/providers/microsoft.guestconfiguration/guestconfigurationassignments"
# Built-in (tenant root), subscription-scoped or management-group-scoped definitions.
_AUTHZ_SCOPE = (
    rf"(?:/subscriptions/{_GUID}|/providers/microsoft\.management/managementgroups/{_SEG})?"
)
_PI = rf"/subscriptions/{_GUID}/providers/microsoft.policyinsights/policystates/latest"

QUERY_PARAMS = frozenset(
    {"$top", "$filter", "$select", "$orderby", "$from", "$to", "$apply", "$skiptoken"}
)


@dataclass(frozen=True)
class SourceRule:
    source_id: str
    method: str
    path_regex: str
    api_version: str
    api_version_status: str
    read_only_query_post: bool = False

    def matches_path(self, path: str) -> bool:
        return re.fullmatch(self.path_regex, path.rstrip("/").lower()) is not None


VERIFIED = "verified-stable-in-research"
UNVERIFIED_PI = "unverified-in-this-work-package"

RULES: tuple[SourceRule, ...] = (
    SourceRule(
        "arg-query",
        "POST",
        r"/providers/microsoft\.resourcegraph/resources",
        "2024-04-01",
        VERIFIED,
        True,
    ),
    SourceRule(
        "policyinsights-querystates",
        "POST",
        rf"{_PI}/queryresults",
        "2024-10-01",
        UNVERIFIED_PI,
        True,
    ),
    SourceRule(
        "policyinsights-summarize",
        "POST",
        rf"{_PI}/summarize",
        "2024-10-01",
        UNVERIFIED_PI,
        True,
    ),
    SourceRule(
        "policy-assignments",
        "GET",
        rf"/subscriptions/{_GUID}/providers/microsoft\.authorization/policyassignments",
        "2023-04-01",
        VERIFIED,
    ),
    SourceRule(
        "policy-exemptions",
        "GET",
        rf"/subscriptions/{_GUID}/providers/microsoft\.authorization/policyexemptions",
        "2022-07-01-preview",
        VERIFIED,
    ),
    SourceRule(
        "policy-definition",
        "GET",
        rf"{_AUTHZ_SCOPE}/providers/microsoft\.authorization/policydefinitions/{_SEG}",
        "2021-06-01",
        VERIFIED,
    ),
    SourceRule(
        "policy-set-definition",
        "GET",
        rf"{_AUTHZ_SCOPE}/providers/microsoft\.authorization/policysetdefinitions/{_SEG}",
        "2021-06-01",
        VERIFIED,
    ),
    SourceRule(
        "defender-secure-scores",
        "GET",
        rf"/subscriptions/{_GUID}/providers/microsoft\.security/securescores",
        "2020-01-01",
        VERIFIED,
    ),
    SourceRule(
        "defender-regulatory-standards",
        "GET",
        rf"/subscriptions/{_GUID}/providers/microsoft\.security/regulatorycompliancestandards",
        "2019-01-01-preview",
        VERIFIED,
    ),
    SourceRule("guestconfig-assignments", "GET", rf"{_MACHINE}{_GC}", "2024-04-05", VERIFIED),
    SourceRule(
        "guestconfig-reports", "GET", rf"{_MACHINE}{_GC}/{_SEG}/reports", "2024-04-05", VERIFIED
    ),
    SourceRule(
        "guestconfig-report-detail",
        "GET",
        rf"{_MACHINE}{_GC}/{_SEG}/reports/{_SEG}",
        "2024-04-05",
        VERIFIED,
    ),
)


class AllowlistViolation(Exception):
    """The request is not an allowlisted read-only operation."""


def match_rule(method: str, host: str, path: str, api_version: str) -> SourceRule:
    if host.lower() != PERMITTED_HOST:
        raise AllowlistViolation(f"host not permitted: {host}")
    for rule in RULES:
        if rule.method == method.upper() and rule.matches_path(path):
            if api_version != rule.api_version:
                raise AllowlistViolation(
                    f"api-version {api_version} not pinned for {rule.source_id}"
                )
            return rule
    raise AllowlistViolation(f"{method.upper()} {path} is not allowlisted")


def validate_continuation(
    link: str, origin: SourceRule, allowed_subscriptions: frozenset[str] | None
) -> str:
    """Validate a nextLink before any credential is attached; returns the safe URL."""
    parts = urlsplit(link)
    if parts.scheme != "https":
        raise AllowlistViolation("continuation link must be https")
    if parts.username or parts.password or parts.port is not None:
        raise AllowlistViolation("continuation link must not carry userinfo or a port")
    if (parts.hostname or "").lower() != PERMITTED_HOST:
        raise AllowlistViolation("continuation link host is not permitted")
    if not origin.matches_path(parts.path):
        raise AllowlistViolation("continuation link path differs from the originating request")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if query.get("api-version") != origin.api_version:
        raise AllowlistViolation("continuation link api-version differs from the pinned version")
    if allowed_subscriptions is not None:
        m = re.match(rf"/subscriptions/({_GUID})/", parts.path.lower() + "/")
        if m and m.group(1) not in allowed_subscriptions:
            raise AllowlistViolation("continuation link subscription is outside the selected scope")
    return link
