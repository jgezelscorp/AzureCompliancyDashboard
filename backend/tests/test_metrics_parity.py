"""Parity: backend metrics == scripts/metrics_reference.py == fixture expectations."""

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.metrics.engine import FAMILIES, compute
from app.models import EvidenceBundle
from tests.conftest import FIXTURES, load_fixture

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "metrics_reference.py"
FIXTURE_NAMES = sorted(p.name for p in FIXTURES.glob("*.json"))


def _load_reference() -> Any:
    spec = importlib.util.spec_from_file_location("metrics_reference", REFERENCE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["metrics_reference"] = mod
    spec.loader.exec_module(mod)
    return mod


reference = _load_reference()


@pytest.mark.parametrize("name", FIXTURE_NAMES)
@pytest.mark.parametrize("family", FAMILIES)
def test_backend_matches_reference(name: str, family: str) -> None:
    raw = load_fixture(name)
    expected = reference.compute(raw, family)
    actual = compute(EvidenceBundle.model_validate(raw), family)
    assert actual == expected


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_backend_matches_fixture_expectations(name: str) -> None:
    raw = load_fixture(name)
    bundle = EvidenceBundle.model_validate(raw)
    for family, exp in (raw.get("expected") or {}).items():
        if family in FAMILIES:
            assert compute(bundle, family) == exp


def test_golden_373_checks_not_reasons() -> None:
    raw = load_fixture("arc-azurewindowsbaseline-373.json")
    result = compute(EvidenceBundle.model_validate(raw), "AzureWindowsBaseline")
    rate = result["checkPassRate"]
    assert (rate["total"], rate["passed"], rate["failed"]) == (373, 109, 264)
    assert rate["percent"] == 29.22
    reasons = sum(len(c["reasons"]) for r in raw["reports"] for c in r["checks"])
    assert reasons == 479 and reasons != rate["total"]


def test_families_never_merge() -> None:
    raw = load_fixture("dual-family-distinct.json")
    bundle = EvidenceBundle.model_validate(raw)
    cis = compute(bundle, "CISWindowsSecurityBaseline")
    assert cis["checkPassRate"]["percent"] is None
    assert cis["machines"][0]["evidenceQuality"] == "MissingAssignment"
    assert not cis["machines"][0]["green"]


def test_stale_and_missing_are_never_green() -> None:
    raw = load_fixture("cis-synthetic-mixed.json")
    bundle = EvidenceBundle.model_validate(raw)
    result = compute(bundle, "CISWindowsSecurityBaseline")
    for m in result["machines"]:
        if m["evidenceQuality"] != "Fresh":
            assert m["green"] is False


def test_empty_estate_has_null_ratios() -> None:
    result = compute(EvidenceBundle.model_validate(load_fixture("empty-estate.json")), FAMILIES[0])
    assert result["policyCompliance"]["percent"] is None
    assert result["checkPassRate"]["percent"] is None
    assert result["coverage"]["assignmentPercent"] is None


def test_freshness_boundary_is_inclusive_24h() -> None:
    raw = load_fixture("dual-family-distinct.json")
    bundle = EvidenceBundle.model_validate(raw)
    end = bundle.reports[0].end_time
    ok = compute(bundle, "AzureWindowsBaseline", end + timedelta(hours=24))
    late = compute(bundle, "AzureWindowsBaseline", end + timedelta(hours=24, seconds=1))
    assert ok["machines"][0]["evidenceQuality"] == "Fresh"
    assert late["machines"][0]["evidenceQuality"] == "Stale"
    assert late["machines"][0]["green"] is False
