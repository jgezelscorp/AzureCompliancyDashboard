"""Security-domain categorization: classifier, API, authorization, overrides, recompute."""

from typing import Any

import pytest
from sqlalchemy import select

from app.api import domains as domains_api
from app.db import CheckRow
from app.domain.domain_store import recompute_domains
from app.domain.domains import (
    classify_check,
    classify_policy,
    frameworks_for,
    load_taxonomy,
    parse_domain_overrides,
    taxonomy_version,
)
from tests.test_metrics_api import AUTH, env

BASE = "/api/v1/domains"
GET_ENDPOINTS = [
    "/taxonomy",
    "/overview",
    "/frameworks",
    "/provenance",
    "/queue",
    "/checks?domain=identity",
    "/overrides",
]


def test_policy_source_category_wins_over_keywords() -> None:
    r = classify_policy("Key Vault", "Audit backup of storage")
    assert (r.domain, r.source, r.confidence) == ("data-protection", "source", "source")


def test_policy_keyword_is_low_confidence() -> None:
    r = classify_policy(None, "Virtual machines should enable backup")
    assert r.domain == "backup-resilience"
    assert (r.source, r.confidence) == ("derived", "derived-low")


def test_policy_unmapped_defaults_to_other() -> None:
    r = classify_policy("Nonexistent Category", "zzz")
    assert (r.domain, r.source, r.confidence) == ("other", "unmapped", "unmapped")


def test_policy_override_beats_source() -> None:
    ov = parse_domain_overrides(
        '[{"target":"policy","type":"prefix","pattern":"audit","domain":"network"}]'
    )
    r = classify_policy("Key Vault", "Audit something", overrides=ov)
    assert (r.domain, r.source, r.confidence) == ("network", "override", "override")


def test_check_section_number_is_derived_high() -> None:
    r = classify_check("18.9.1 Something", benchmark_control_id="2.2.3")
    assert r.domain == "identity"
    assert r.confidence == "derived-high"


def test_check_source_category_wins_over_section() -> None:
    r = classify_check("x", benchmark_control_id="2.2.3", source_category="Network")
    assert (r.domain, r.source) == ("network", "source")


def test_check_unmapped() -> None:
    r = classify_check("synth-check-001")
    assert r.confidence == "unmapped"


def test_invalid_override_rejected() -> None:
    with pytest.raises(ValueError):
        parse_domain_overrides('[{"target":"policy","pattern":"a","domain":"nope"}]')


def test_crosswalk_only_references_known_families() -> None:
    t = load_taxonomy()
    assert t.version == taxonomy_version()
    for domain in t.labels:
        for fw, families in frameworks_for(domain).items():
            assert families, (domain, fw)


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_domain_endpoints_require_bearer(path: str) -> None:
    e = env()
    assert e.client.get(BASE + path).status_code == 401


def test_taxonomy_has_disclaimer_and_nine_domains() -> None:
    e = env()
    body = e.client.get(f"{BASE}/taxonomy", headers=AUTH).json()
    assert len(body["domains"]) == 9
    assert "not" in body["disclaimer"].lower()


def test_overview_and_frameworks_are_non_additive() -> None:
    e = env()
    ov = e.client.get(f"{BASE}/overview", headers=AUTH).json()
    assert ov["taxonomyVersion"] == taxonomy_version()
    checks_total = sum(f["checks"] for d in ov["domains"] for f in d["machine"].values())
    assert checks_total == 373
    fw = e.client.get(f"{BASE}/frameworks", headers=AUTH).json()
    assert fw["additive"] is False


def test_queue_lists_unmapped_checks_with_pagination() -> None:
    e = env()
    body = e.client.get(f"{BASE}/queue?kind=check&limit=5", headers=AUTH).json()
    assert len(body["rows"]) <= 5
    assert body["total"] >= 1
    assert all(i["domainConfidence"] in ("unmapped", "derived-low") for i in body["rows"])


def test_rows_filtered_before_aggregation() -> None:
    e = env()
    e.arm.routes = {"/subscriptions": [{"value": []}]}
    ov = e.client.get(f"{BASE}/overview", headers=AUTH)
    body: Any = ov.json()
    if ov.status_code == 200:
        assert all(not d["machine"] for d in body["domains"])
        assert all(not d["policy"] for d in body["domains"])
        assert body["provenance"]["checks"]["total"] == 0
    else:
        assert ov.status_code in (403, 404)


def test_override_denied_without_deployments_write() -> None:
    e = env()
    r = e.client.post(
        f"{BASE}/overrides",
        headers=AUTH,
        json={"target": "check", "pattern": "synth-check-001", "domain": "network"},
    )
    assert r.status_code == 403
    assert "not permitted" in r.json()["detail"]


def test_override_create_recompute_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    e = env()
    monkeypatch.setattr(domains_api, "can_edit_shared_config", lambda *a, **k: (True, "ok"))
    r = e.client.post(
        f"{BASE}/overrides",
        headers=AUTH,
        json={"target": "check", "pattern": "synth-check-001", "domain": "network"},
    )
    assert r.status_code == 201, r.text
    with e.factory() as s:
        row = s.scalars(select(CheckRow).where(CheckRow.check_key == "synth-check-001")).first()
        assert row is not None
        assert (row.domain, row.domain_source) == ("network", "override")
    bad = e.client.post(
        f"{BASE}/overrides",
        headers=AUTH,
        json={"target": "check", "pattern": "x", "domain": "bogus"},
    )
    assert bad.status_code == 422
    assert e.client.delete(f"{BASE}/overrides/{r.json()['id']}", headers=AUTH).status_code == 204
    with e.factory() as s:
        row = s.scalars(select(CheckRow).where(CheckRow.check_key == "synth-check-001")).first()
        assert row is not None
        assert row.domain_source != "override"


def test_recompute_on_version_change_keeps_raw_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    e = env()
    with e.factory() as s:
        before = [
            (c.check_key, c.compliance_status, c.category) for c in s.scalars(select(CheckRow))
        ]
        for c in s.scalars(select(CheckRow)):
            c.domain_version = 0
        s.commit()
        counts = recompute_domains(s)
        s.commit()
        assert counts["checks"] > 0
        after = [
            (c.check_key, c.compliance_status, c.category) for c in s.scalars(select(CheckRow))
        ]
        assert before == after
        assert all(c.domain_version == taxonomy_version() for c in s.scalars(select(CheckRow)))
