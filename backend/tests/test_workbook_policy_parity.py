"""Parity: the policy-estate KQL aggregates (70/71/72) == the backend tally() over synthetic states.

The KQL is evaluated with a tiny row-level model of its summarize semantics over synthetic
Resource Graph policystate rows. No real tenant data.
"""
import sys
from pathlib import Path
from typing import Any

from app.metrics.policy import tally

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from workbook_lib import load_queries  # type: ignore[import-not-found]  # noqa: E402

Row = tuple[str, str, str, str]
ROWS: list[Row] = [
    ("/subscriptions/s1/resourcegroups/rg1/providers/t/a", "Compliant", "def-1", "init-1"),
    ("/subscriptions/s1/resourcegroups/rg1/providers/t/a", "NonCompliant", "def-2", "init-1"),
    ("/subscriptions/s1/resourcegroups/rg1/providers/t/b", "NonCompliant", "def-2", "init-1"),
    ("/subscriptions/s1/resourcegroups/rg1/providers/t/b", "NonCompliant", "def-3", ""),
    ("/subscriptions/s1/resourcegroups/rg2/providers/t/c", "Exempt", "def-1", "init-1"),
    ("/subscriptions/s1/resourcegroups/rg2/providers/t/c", "Unknown", "def-4", ""),
    ("/subscriptions/s1/resourcegroups/rg2/providers/t/d", "Compliant", "def-4", ""),
]


def kql_overview(rows: list[Row]) -> dict[str, Any]:
    c = sum(r[1].lower() == "compliant" for r in rows)
    nc = sum(r[1].lower() == "noncompliant" for r in rows)
    ex = sum(r[1].lower() == "exempt" for r in rows)
    other = sum(r[1].lower() not in ("compliant", "noncompliant", "exempt") for r in rows)
    ncr = len({r[0].lower() for r in rows if r[1].lower() == "noncompliant"})
    percent = None if c + nc == 0 else round(100.0 * c / (c + nc), 2)
    return {
        "compliant": c, "nonCompliant": nc, "exempt": ex, "otherStates": other,
        "nonCompliantResources": ncr, "policyCompliancePercent": percent,
    }


def backend_view(rows: list[Row]) -> dict[str, Any]:
    t = tally([{"rid": r[0].lower(), "state": r[1], "definition": r[2]} for r in rows])
    return {
        "compliant": t["compliant"], "nonCompliant": t["nonCompliant"], "exempt": t["exempt"],
        "otherStates": t["other"], "nonCompliantResources": t["nonCompliantResources"],
        "policyCompliancePercent": t["percent"],
    }


def test_overview_aggregate_matches_backend_tally() -> None:
    assert kql_overview(ROWS) == backend_view(ROWS)


def test_initiative_group_matches_backend_tally() -> None:
    for init in ("init-1", ""):
        rows = [r for r in ROWS if r[3] == init]
        assert kql_overview(rows) == backend_view(rows)


def test_no_data_is_null_not_zero() -> None:
    rows = [r for r in ROWS if r[1] in ("Exempt", "Unknown")]
    assert kql_overview(rows)["policyCompliancePercent"] is None
    assert backend_view(rows)["policyCompliancePercent"] is None


def test_policy_queries_use_documented_state_formula() -> None:
    queries = {q["id"]: q["query"] for q in load_queries()}
    for qid in ("pol-overview", "pol-initiative", "pol-resourcetype"):
        text = queries[qid]
        assert "compliant + nonCompliant == 0, real(null)" in text, qid
        assert "100.0 * compliant / (compliant + nonCompliant)" in text, qid
        assert "microsoft.policyinsights/policystates" in text, qid
    assert "state !in~ ('Compliant', 'NonCompliant', 'Exempt')" in queries["pol-overview"]
