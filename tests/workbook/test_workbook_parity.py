"""Workbook parity: KQL-equivalent logic over fixtures == scripts/metrics_reference.py.

Run: pip install pytest jsonschema ; pytest tests/workbook
"""
import copy
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "scripts"))

import kql_model  # noqa: E402
from workbook_lib import load_queries  # noqa: E402

spec = importlib.util.spec_from_file_location("metrics_reference", ROOT / "scripts" / "metrics_reference.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)

FIXTURES = sorted((ROOT / "tests" / "fixtures").glob("*.json"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def reference_view(bundle, family):
    ref = reference.compute(bundle, family)
    return {
        "policyCompliance": ref["policyCompliance"], "checkPassRate": ref["checkPassRate"],
        "coverage": ref["coverage"],
        "machines": [{"machineId": m["machineId"], "evidenceQuality": m["evidenceQuality"],
                      "reportedState": m["reportedState"], "green": m["green"]} for m in ref["machines"]],
    }


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
@pytest.mark.parametrize("family", kql_model.FAMILIES)
def test_kql_logic_matches_reference(path, family):
    bundle = load(path)
    assert kql_model.run(bundle)[family] == reference_view(bundle, family)


def test_golden_373_checks_not_reasons():
    bundle = load(ROOT / "tests" / "fixtures" / "arc-azurewindowsbaseline-373.json")
    rate = kql_model.run(bundle)["AzureWindowsBaseline"]["checkPassRate"]
    assert (rate["total"], rate["passed"], rate["failed"], rate["percent"]) == (373, 109, 264, 29.22)
    reasons = sum(len(c["reasons"]) for r in bundle["reports"] for c in r["checks"])
    assert reasons == 479 and reasons != rate["total"]


def test_families_stay_separate_and_baseline_is_not_cis():
    bundle = load(ROOT / "tests" / "fixtures" / "dual-family-distinct.json")
    cis = kql_model.run(bundle)["CISWindowsSecurityBaseline"]
    assert cis["checkPassRate"]["percent"] is None
    assert cis["machines"][0]["evidenceQuality"] == "MissingAssignment" and not cis["machines"][0]["green"]


def test_stale_unknown_and_missing_are_never_green():
    bundle = load(ROOT / "tests" / "fixtures" / "cis-synthetic-mixed.json")
    for family in kql_model.FAMILIES:
        for m in kql_model.run(bundle)[family]["machines"]:
            if m["evidenceQuality"] != "Fresh":
                assert m["green"] is False


def test_freshness_boundary_inclusive_24h_and_unknown_age():
    bundle = load(ROOT / "tests" / "fixtures" / "dual-family-distinct.json")
    end = kql_model.ts(bundle["reports"][0]["endTime"])
    fam = "AzureWindowsBaseline"
    ok = kql_model.run(bundle, now=end + timedelta(hours=24))[fam]["machines"][0]
    late = kql_model.run(bundle, now=end + timedelta(hours=24, seconds=1))[fam]["machines"][0]
    assert ok["evidenceQuality"] == "Fresh" and late["evidenceQuality"] == "Stale" and not late["green"]
    mutated = copy.deepcopy(bundle)
    mutated["reports"][0]["endTime"] = None
    row = kql_model.run(mutated)[fam]["machines"][0]
    assert row["evidenceQuality"] == "UnknownAge" and not row["green"]


def test_empty_estate_is_null_not_zero():
    result = kql_model.run(load(ROOT / "tests" / "fixtures" / "empty-estate.json"))
    for family in kql_model.FAMILIES:
        assert result[family]["policyCompliance"]["percent"] is None
        assert result[family]["checkPassRate"]["percent"] is None
        assert result[family]["coverage"]["assignmentPercent"] is None


def test_duplicate_machine_names_across_scopes_stay_distinct():
    bundle = load(ROOT / "tests" / "fixtures" / "dual-family-distinct.json")
    twin = copy.deepcopy(bundle)
    old = bundle["machines"][0]["machineId"]
    new = old.replace("/resourcegroups/", "/resourcegroups/other-", 1)
    for key in ("machines", "assignments", "reports"):
        for row in twin[key]:
            for field, value in list(row.items()):
                if isinstance(value, str) and old in value:
                    row[field] = value.replace(old, new)
    bundle["machines"] += twin["machines"]
    bundle["assignments"] += twin["assignments"]
    bundle["reports"] += twin["reports"]
    machines = kql_model.run(bundle)["AzureWindowsBaseline"]["machines"]
    assert len({m["machineId"] for m in machines}) == 2
    assert kql_model.run(bundle)["AzureWindowsBaseline"] == reference_view(bundle, "AzureWindowsBaseline")


def test_kql_text_carries_contract_constants():
    joined = "\n".join(q["query"] for q in load_queries())
    assert f"ageSeconds <= {int(reference.STALE_AFTER.total_seconds())}" in joined
    assert "arg_max(rank" in joined and "real(null)" in joined
    assert "isnotempty(checkKey)" in joined and "quality == 'Fresh'" in joined
    # the model and the KQL classify the same quality values
    for quality in ("UnknownApplicability", "MissingAssignment", "NoReport", "UnknownAge", "Fresh", "Stale"):
        assert f"'{quality}'" in joined


def _log_rows():
    t0 = kql_model.ts("2025-01-10T12:00:00Z")
    runs = [{"TimeGenerated": t0}]
    mk = lambda rid, machine, end: {  # noqa: E731
        "ReportId": rid, "MachineId": machine, "Family": "AzureWindowsBaseline", "ReportEndTime": end}
    reports = [
        mk(1, "m1", t0 - timedelta(hours=1)), mk(2, "m1", t0 - timedelta(hours=1)),  # tie -> min id
        mk(3, "m2", t0 - timedelta(hours=25)),  # stale vs the latest stored snapshot
        mk(4, "m3", t0 - timedelta(hours=2)),
    ]
    chk = lambda rid, key, st, cat=None: {  # noqa: E731
        "ReportId": rid, "CheckKey": key, "ComplianceStatus": st, "Category": cat}
    checks = [chk(1, "a", "Compliant", "Net"), chk(1, "a", "Compliant", "Net"),  # retry duplicate
              chk(1, "b", "NonCompliant"), chk(2, "a", "NonCompliant"), chk(3, "a", "Compliant"),
              chk(4, "a", "Compliant")]
    return runs, reports, checks


def test_logs_history_dedupes_retries_and_picks_one_report_per_machine():
    out = kql_model.logs_fresh_checks(*_log_rows())
    assert {(c["machineId"], c["checkKey"]) for c in out} == {("m1", "a"), ("m1", "b"), ("m3", "a")}
    assert [c["category"] for c in out if c["checkKey"] == "b"] == ["Uncategorized"]


def test_logs_history_excludes_stale_relative_to_latest_snapshot_not_now():
    out = kql_model.logs_fresh_checks(*_log_rows())
    assert all(c["machineId"] != "m2" for c in out)


def test_logs_queries_read_only_reporting_tables_and_show_lag():
    logs = [q for q in load_queries() if q["source"] == "logs"]
    assert {q["tab"] for q in logs} == {"history"} and len(logs) >= 6
    joined = "\n".join(q["query"] for q in logs)
    assert "ingestion_time()" in joined and "min(ReportId)" in joined and "latestSnapshot - 24h" in joined
    assert not [q for q in load_queries() if q["source"] == "arg" and "_CL" in q["query"]]
