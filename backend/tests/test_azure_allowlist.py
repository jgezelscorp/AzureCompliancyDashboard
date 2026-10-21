"""Read-only allowlist: default deny, pinned api-versions, continuation-link validation."""

import pytest

from app.azure.allowlist import (
    RULES,
    AllowlistViolation,
    match_rule,
    validate_continuation,
)

SUB = "00000000-0000-0000-0000-000000000000"
OTHER = "11111111-1111-1111-1111-111111111111"
HOST = "management.azure.com"
MACHINE = (
    f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
)
GC = "/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments"
PI = f"/subscriptions/{SUB}/providers/Microsoft.PolicyInsights/policyStates/latest"


@pytest.mark.parametrize(
    ("method", "path", "version", "source"),
    [
        ("POST", "/providers/Microsoft.ResourceGraph/resources", "2024-04-01", "arg-query"),
        ("POST", f"{PI}/queryResults", "2024-10-01", "policyinsights-querystates"),
        ("POST", f"{PI}/summarize", "2024-10-01", "policyinsights-summarize"),
        ("GET", f"{MACHINE}{GC}", "2024-04-05", "guestconfig-assignments"),
        ("GET", f"{MACHINE}{GC}/a/reports", "2024-04-05", "guestconfig-reports"),
        ("GET", f"{MACHINE}{GC}/a/reports/r1", "2024-04-05", "guestconfig-report-detail"),
        ("get", f"{MACHINE}{GC}/", "2024-04-05", "guestconfig-assignments"),
    ],
)
def test_allowed_operations(method: str, path: str, version: str, source: str) -> None:
    assert match_rule(method, HOST, path, version).source_id == source


@pytest.mark.parametrize(
    ("method", "host", "path", "version"),
    [
        ("PUT", HOST, f"{MACHINE}{GC}/a", "2024-04-05"),
        ("DELETE", HOST, f"{MACHINE}{GC}/a", "2024-04-05"),
        ("PATCH", HOST, f"{MACHINE}{GC}/a", "2024-04-05"),
        ("POST", HOST, f"{MACHINE}{GC}", "2024-04-05"),
        ("GET", HOST, "/providers/Microsoft.ResourceGraph/resources", "2024-04-01"),
        ("POST", HOST, f"{PI}/triggerEvaluation", "2024-10-01"),
        ("POST", HOST, f"/subscriptions/{SUB}/providers/Microsoft.PolicyInsights/other", "x"),
        ("GET", "evil.example", f"{MACHINE}{GC}", "2024-04-05"),
        ("GET", "management.azure.com.evil.example", f"{MACHINE}{GC}", "2024-04-05"),
        ("GET", HOST, f"{MACHINE}{GC}", "2020-01-01"),
        ("GET", HOST, "/subscriptions/not-a-guid/resourceGroups/rg/x", "2024-04-05"),
        ("GET", HOST, f"{MACHINE}/extensions", "2024-04-05"),
    ],
)
def test_everything_else_is_denied(method: str, host: str, path: str, version: str) -> None:
    with pytest.raises(AllowlistViolation):
        match_rule(method, host, path, version)


def test_only_three_query_posts_and_no_other_write_methods() -> None:
    assert {r.method for r in RULES} == {"GET", "POST"}
    posts = [r for r in RULES if r.method == "POST"]
    assert len(posts) == 3 and all(r.read_only_query_post for r in posts)
    assert not any(r.read_only_query_post for r in RULES if r.method == "GET")


def test_unverified_api_versions_stay_marked() -> None:
    by = {r.source_id: r for r in RULES}
    assert by["policyinsights-querystates"].api_version_status.startswith("unverified")
    assert by["guestconfig-reports"].api_version_status.startswith("verified")


def origin() -> object:
    return match_rule("GET", HOST, f"{MACHINE}{GC}/a/reports", "2024-04-05")


def link(path: str = f"{MACHINE}{GC}/a/reports", **over: str) -> str:
    base = {"scheme": "https", "host": HOST, "version": "2024-04-05"}
    base.update(over)
    return f"{base['scheme']}://{base['host']}{path}?api-version={base['version']}&$skiptoken=abc"


def test_valid_continuation_is_returned() -> None:
    rule = match_rule("GET", HOST, f"{MACHINE}{GC}/a/reports", "2024-04-05")
    ok = link()
    assert validate_continuation(ok, rule, frozenset([SUB])) == ok


@pytest.mark.parametrize(
    "bad",
    [
        link(scheme="http"),
        link(host="evil.example"),
        link(host=f"user:pw@{HOST}"),
        link(host=f"{HOST}:8443"),
        link(host=f"{HOST}.evil.example"),
        link(path=f"{MACHINE}{GC}/a"),
        link(path=f"{MACHINE}{GC}/a/reports/extra/segments"),
        link(version="2023-01-01"),
        link(path=f"/subscriptions/{OTHER}/resourceGroups/rg/providers/Microsoft.Compute"
             f"/virtualMachines/vm1{GC}/a/reports"),
    ],
)
def test_malicious_continuations_rejected(bad: str) -> None:
    rule = match_rule("GET", HOST, f"{MACHINE}{GC}/a/reports", "2024-04-05")
    with pytest.raises(AllowlistViolation):
        validate_continuation(bad, rule, frozenset([SUB]))


def test_continuation_without_scope_restriction_still_checks_path() -> None:
    rule = match_rule("GET", HOST, f"{MACHINE}{GC}/a/reports", "2024-04-05")
    other = f"/subscriptions/{OTHER}/resourceGroups/rg/providers/Microsoft.Compute"
    other += f"/virtualMachines/vm1{GC}/a/reports"
    assert validate_continuation(link(path=other), rule, None)
