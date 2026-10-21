"""Estate-wide Azure Policy metrics on synthetic states (pure functions, no database)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.collectors import estate
from app.metrics import policy

NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)


def st(
    rid: str,
    state: str,
    definition: str = "d1",
    *,
    initiative: str = "init-a",
    rtype: str = "microsoft.storage/storageaccounts",
    sub: str = "sub-1",
    rg: str = "rg-a",
    effect: str = "audit",
    severity: str | None = None,
    age_h: int = 1,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "rid": rid,
        "sub": sub,
        "rg": rg,
        "loc": "westeurope",
        "rtype": rtype,
        "assignment": f"/assign/{initiative}",
        "assignmentName": initiative,
        "definition": definition,
        "definitionName": definition.upper(),
        "ref": None,
        "initiative": initiative,
        "initiativeName": initiative.upper(),
        "state": state,
        "effect": effect,
        "category": "Storage",
        "severity": severity,
        "ts": NOW - timedelta(hours=age_h),
        "groups": [],
        "resourceName": rid,
        "tags": tags or {},
    }


STATES = [
    st("r1", "Compliant"),
    st("r1", "NonCompliant", "d2", severity="high", effect="deny"),
    st("r2", "NonCompliant"),
    st("r3", "Compliant", initiative="init-b", rtype="microsoft.compute/virtualmachines"),
    st("r4", "Unknown", initiative="init-b"),
    st("r5", "Exempt", age_h=100),
]


def test_tally_percent_excludes_exempt_and_other() -> None:
    t = policy.tally(STATES)
    assert (t["compliant"], t["nonCompliant"], t["exempt"], t["other"]) == (2, 2, 1, 1)
    assert t["percent"] == 50.0
    assert t["evaluations"] == 6


def test_no_data_percent_is_none_not_green() -> None:
    assert policy.tally([st("x", "Unknown")])["percent"] is None
    assert policy.tally([])["percent"] is None


def test_headline_resource_grain_differs_from_evaluation_grain() -> None:
    h = policy.headline(STATES)
    assert h["resourcesCounted"] == 3  # r1, r2, r3 (r4 unknown, r5 exempt are not counted)
    assert h["resourcesFullyCompliant"] == 1
    assert h["resourcePercent"] == 33.33
    assert h["highImpactFailingPolicies"] == 1
    assert h["enforcementFailingPolicies"] == 1


def test_breakdown_sorts_missing_percent_last() -> None:
    rows = policy.breakdown(STATES, "initiative", sort="percent", descending=False)
    assert [r["key"] for r in rows][-1] != ""
    only_unknown = policy.breakdown(
        [st("z", "Unknown", initiative="init-z")] + STATES, "initiative", "percent", False
    )
    assert only_unknown[-1]["key"] == "init-z"


def test_breakdown_by_tag_and_untagged() -> None:
    states = [st("a", "NonCompliant", tags={"owner": "team-x"}), st("b", "NonCompliant")]
    rows = {r["key"]: r for r in policy.breakdown(states, "tag:owner")}
    assert rows["team-x"]["nonCompliant"] == 1
    assert rows[policy.UNTAGGED]["nonCompliant"] == 1


def test_top_policies_ranks_by_affected_resources() -> None:
    top = policy.top_policies(STATES)
    assert [t["definition"] for t in top] == ["d1", "d2"]
    assert top[0]["affectedResources"] == 1


def test_filter_before_aggregation() -> None:
    f = policy.StateFilter(initiative=("init-b",))
    got = policy.apply_filter(STATES, f, NOW)
    assert {s["rid"] for s in got} == {"r3", "r4"}
    assert policy.tally(got)["nonCompliant"] == 0
    old = policy.apply_filter(STATES, policy.StateFilter(min_age_hours=24), NOW)
    assert [s["rid"] for s in old] == ["r5"]


def test_filter_tag_and_search() -> None:
    states = [st("a", "Compliant", tags={"environment": "prod"}), st("b", "Compliant")]
    assert len(policy.apply_filter(states, policy.StateFilter(tag=("environment:prod",)), NOW)) == 1
    assert len(policy.apply_filter(states, policy.StateFilter(q="b"), NOW)) == 1


def test_freshness_counts_threshold() -> None:
    f = policy.freshness(STATES, NOW, 24)
    assert f["fresh"] == 5 and f["evaluations"] == 6
    assert policy.freshness([], NOW, 24)["percent"] is None


def test_exemption_buckets_are_exclusive() -> None:
    def ex(days: int | None) -> dict[str, Any]:
        return {
            "id": f"e{days}",
            "name": "n",
            "scope": "s",
            "assignment": "a",
            "category": "Waiver",
            "expiresOn": None if days is None else NOW + timedelta(days=days, hours=1),
        }

    out = policy.exemption_summary([ex(5), ex(45), ex(75), ex(200), ex(-3), ex(None)], NOW)
    b = out["buckets"]
    assert (b["expiring30"], b["expiring60"], b["expiring90"]) == (1, 1, 1)
    assert b["expired"] == 1 and b["active"] == 5 and b["noExpiry"] == 1
    assert out["total"] == 6


def test_diff_states_regressions_and_recoveries() -> None:
    old = {
        ("r1", "a", ""): "Compliant",
        ("r2", "a", ""): "NonCompliant",
        ("r3", "a", ""): "NonCompliant",
    }
    new = {
        ("r1", "a", ""): "NonCompliant",
        ("r2", "a", ""): "Compliant",
        ("r4", "a", ""): "NonCompliant",
    }
    d = policy.diff_states(old, new)
    assert d["regressions"] == 1 and d["recoveries"] == 1
    assert d["newNonCompliant"] == 1 and d["noLongerReportedNonCompliant"] == 1


def test_snapshot_metrics_has_no_composite_score() -> None:
    m = policy.snapshot_metrics(STATES, [], 10, NOW, None)
    assert "score" not in str(m.keys()).lower()
    assert m["inventory"] == 10 and "init-a" in m["byInitiative"]


def test_sanitize_parameters_redacts_secret_like_names() -> None:
    out = estate.sanitize_parameters(
        {
            "effect": {"value": "Audit"},
            "adminPassword": {"value": "hunter2"},
            "apiKey": {"value": "k"},
        }
    )
    assert out is not None
    assert out["effect"] == "Audit"
    assert "hunter2" not in str(out) and "'k'" not in str(out)


def test_state_extras_ignores_tbd_category() -> None:
    ex = estate.state_extras({"policyDefinitionCategory": "tbd", "policyDefinitionAction": "Audit"})
    assert ex.get("category") is None
    assert str(ex.get("effect")).lower() == "audit"


def test_inventory_keeps_only_whitelisted_tags() -> None:
    row = {
        "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/x",
        "name": "x",
        "type": "microsoft.storage/storageaccounts",
        "subscriptionId": "s",
        "resourceGroup": "rg",
        "location": "westeurope",
        "tags": {"Owner": "team", "email": "someone@example.com"},
    }
    out = estate.normalize_inventory(row, ["owner"])
    assert out is not None
    assert out["tags"] == {"owner": "team"}
