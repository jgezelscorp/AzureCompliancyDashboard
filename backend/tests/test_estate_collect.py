"""Collector persists the estate-wide policy data (synthetic transport, no live Azure)."""

from typing import Any

from sqlalchemy import select

from app.db_history import PolicyStateRow
from app.db_policy import (
    EstateSnapshotRow,
    PolicyAssignmentRow,
    PolicyDefinitionRow,
    PolicyExemptionRow,
)
from app.metrics import policy
from tests.conftest import load_fixture
from tests.test_collector_run import SUB, make_runner

DEF_ID = "/providers/Microsoft.Authorization/policyDefinitions/synth-def-1"
ASSIGN_ID = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyAssignments/synth-a"
STORAGE = (
    f"/subscriptions/{SUB}/resourcegroups/rg-synthetic"
    "/providers/microsoft.storage/storageaccounts/stsynth"
)


def estate_bundle() -> dict[str, Any]:
    bundle = load_fixture("dual-family-distinct.json")
    bundle["policyStates"].append(
        {
            "resourceId": STORAGE,
            "policyAssignmentId": ASSIGN_ID,
            "policyDefinitionId": DEF_ID,
            "policyDefinitionReferenceId": None,
            "complianceState": "NonCompliant",
            "isCompliant": False,
            "timestamp": bundle["snapshotAt"],
            "resourceType": "Microsoft.Storage/storageAccounts",
            "resourceGroup": "rg-synthetic",
            "resourceLocation": "swedencentral",
            "policyAssignmentName": "synth-a",
            "policyDefinitionName": "synth-def-1",
            "policyDefinitionAction": "audit",
            "policyDefinitionCategory": "tbd",
        }
    )
    bundle["policyAssignments"] = [
        {
            "id": ASSIGN_ID,
            "name": "synth-a",
            "properties": {
                "displayName": "Synthetic assignment",
                "policyDefinitionId": DEF_ID,
                "scope": f"/subscriptions/{SUB}",
                "enforcementMode": "Default",
                "parameters": {"adminPassword": {"value": "hunter2"}},
            },
        }
    ]
    bundle["policyExemptions"] = [
        {
            "id": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyExemptions/ex1",
            "name": "ex1",
            "properties": {
                "displayName": "Synthetic waiver",
                "exemptionCategory": "Waiver",
                "policyAssignmentId": ASSIGN_ID,
                "expiresOn": "2030-01-01T00:00:00Z",
            },
        }
    ]
    bundle["policyDefinitions"] = {
        "synth-def-1": {
            "id": DEF_ID,
            "name": "synth-def-1",
            "properties": {
                "displayName": "Synthetic definition",
                "policyType": "BuiltIn",
                "metadata": {"category": "Storage", "severity": "high"},
                "policyRule": {"then": {"effect": "audit"}},
            },
        }
    }
    return bundle


def test_collector_persists_estate_tables_and_snapshot() -> None:
    bundle = estate_bundle()
    runner, _fake, factory = make_runner(bundle)
    result = runner.run_once()
    assert result is not None and result.status == "succeeded", result
    with factory() as s:
        row = s.scalars(select(PolicyStateRow).where(PolicyStateRow.resource_id == STORAGE)).one()
        assert row.resource_type == "Microsoft.Storage/storageAccounts"
        assert row.resource_group == "rg-synthetic"
        assert row.effect == "audit"
        assert row.state_category is None  # the literal "tbd" is not a category
        assert s.scalars(select(PolicyAssignmentRow)).one().display_name == "Synthetic assignment"
        assert s.scalars(select(PolicyExemptionRow)).one().category == "Waiver"
        with_sev = select(PolicyDefinitionRow).where(PolicyDefinitionRow.severity.is_not(None))
        assert s.scalars(with_sev).one().severity == "High"
        snap = s.scalars(select(EstateSnapshotRow)).one()
        assert snap.metrics["headline"]["nonCompliant"] >= 1
        assert "hunter2" not in str(s.scalars(select(PolicyAssignmentRow)).one().parameters)

        data = policy.load_estate(s, frozenset([SUB]))
        mine = [x for x in data.states if x["rid"] == STORAGE.lower() or x["rid"] == STORAGE]
        assert mine and mine[0]["category"] == "Storage" and mine[0]["severity"] == "high"
        assert policy.headline(data.states)["highImpactFailingPolicies"] >= 1


def test_authorization_filters_rows_before_aggregation() -> None:
    bundle = estate_bundle()
    runner, _fake, factory = make_runner(bundle)
    assert runner.run_once() is not None
    with factory() as s:
        assert policy.load_estate(s, frozenset()).states == []
        other = policy.load_estate(s, frozenset(["11111111-1111-1111-1111-111111111111"]))
        assert other.states == [] and other.exemptions == []
        assert policy.headline(other.states)["percent"] is None


def test_unavailable_defender_and_definitions_do_not_fail_run() -> None:
    bundle = estate_bundle()
    bundle["policyDefinitions"] = {}
    runner, _fake, _factory = make_runner(bundle)
    result = runner.run_once()
    assert result is not None and result.status == "succeeded", result
