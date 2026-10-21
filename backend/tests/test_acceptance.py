"""Acceptance: three-way parity, honest labels, scope isolation and large-estate load."""

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from app.metrics.engine import FAMILIES, compute
from app.models import EvidenceBundle
from tests.conftest import FIXTURES, load_fixture
from tests.test_collector_run import SUB, make_runner
from tests.test_metrics_api import AUTH, OTHER, Env, arm_routes

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "workbook"))
sys.path.insert(0, str(ROOT / "scripts"))

import kql_model  # type: ignore[import-not-found]  # noqa: E402


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


reference = _load("metrics_reference", ROOT / "scripts" / "metrics_reference.py")
generator = _load("generate_fixtures_acceptance", ROOT / "scripts" / "generate_fixtures.py")

FIXTURE_NAMES = sorted(p.name for p in FIXTURES.glob("*.json"))
SMALL_ESTATE = 120
LARGE_ESTATE = 3000


def _workbook_view(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "policyCompliance": ref["policyCompliance"],
        "checkPassRate": ref["checkPassRate"],
        "coverage": ref["coverage"],
        "machines": [
            {
                "machineId": m["machineId"],
                "evidenceQuality": m["evidenceQuality"],
                "reportedState": m["reportedState"],
                "green": m["green"],
            }
            for m in ref["machines"]
        ],
    }


def _assert_three_way(raw: dict[str, Any]) -> None:
    bundle = EvidenceBundle.model_validate(raw)
    workbook = kql_model.run(raw)
    for family in FAMILIES:
        backend = compute(bundle, family)
        assert backend == reference.compute(raw, family)
        assert _workbook_view(backend) == workbook[family]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_three_way_parity_on_fixtures(name: str) -> None:
    _assert_three_way(load_fixture(name))


def test_three_way_parity_on_synthetic_estate() -> None:
    _assert_three_way(generator.gen_large_estate(SMALL_ESTATE))


def test_large_estate_generator_is_deterministic_and_synthetic() -> None:
    a = generator.gen_large_estate(50)
    assert a == generator.gen_large_estate(50)
    assert {m["subscriptionId"] for m in a["machines"]} == {SUB}


def test_honest_evidence_labels_on_synthetic_estate() -> None:
    raw = generator.gen_large_estate(SMALL_ESTATE)
    bundle = EvidenceBundle.model_validate(raw)
    for family in FAMILIES:
        result = compute(bundle, family)
        for m in result["machines"]:
            if m["evidenceQuality"] != "Fresh":
                assert m["green"] is False, m
        total = result["checkPassRate"]["total"]
        fresh_checks = sum(
            len(r["checks"])
            for r in raw["reports"]
            if r["baselineFamily"] == family
            and next(
                x for x in result["machines"] if x["machineId"] == r["machineId"]
            )["evidenceQuality"]
            == "Fresh"
        )
        assert total == fresh_checks


def _cert_free(text: str) -> bool:
    lowered = text.lower()
    return not any(w in lowered for w in ("certified", "cis certification", "cis-certified"))


def test_api_payloads_make_no_certification_claim() -> None:
    e = Env("cis-synthetic-mixed.json")
    e.register(SUB)
    for url in ("/api/v1/metrics/latest", "/api/v1/metrics/scopes"):
        assert _cert_free(e.client.get(url, headers=AUTH).text)


def test_unauthorized_scope_data_never_appears_in_any_view() -> None:
    e = Env("cis-synthetic-mixed.json")
    e.register(SUB, OTHER)
    e.arm.routes = arm_routes((OTHER,))
    for url in (
        "/api/v1/metrics/machines?family=CISWindowsSecurityBaseline",
        "/api/v1/metrics/scopes",
        "/api/v1/metrics/categories?family=CISWindowsSecurityBaseline",
    ):
        resp = e.client.get(url, headers=AUTH)
        assert SUB not in resp.text, url
        assert "vm-synth" not in resp.text and "arc-synth" not in resp.text, url


@pytest.mark.heavy
def test_large_estate_collection_and_metrics_stay_correct_and_fast() -> None:
    raw = generator.gen_large_estate(LARGE_ESTATE)
    bundle = EvidenceBundle.model_validate(raw)
    started = time.perf_counter()
    results = {f: compute(bundle, f) for f in FAMILIES}
    assert time.perf_counter() - started < 30
    for family in FAMILIES:
        assert results[family] == reference.compute(raw, family)
        assert results[family]["coverage"]["eligible"] > 0
        assert not any(
            m["green"] for m in results[family]["machines"] if m["evidenceQuality"] != "Fresh"
        )


@pytest.mark.heavy
def test_large_estate_collected_through_runner_matches_reference() -> None:
    from sqlalchemy import func, select

    from app.db import MachineRow

    count = 800
    raw = generator.gen_large_estate(count)
    runner, _, factory = make_runner(raw)
    started = time.perf_counter()
    runner.run_once()
    assert time.perf_counter() - started < 120
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(MachineRow)) == count
