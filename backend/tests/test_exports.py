"""Export jobs: authorization on create/download, leakage, injection, expiry, audit."""

import io
import re
from datetime import timedelta
from typing import Any

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.api import exports
from app.api.metrics import _now
from app.auth import deps
from app.db import MachineRow
from app.db_exports import ExportAuditRow, ExportJobRow
from app.db_history import MachineStatusSnapshotRow, MetricSnapshotRow
from app.exporters import PdfDoc, build_csv, csv_cell, pdf_text
from tests.test_auth import FakeArm, make_token
from tests.test_collector_run import SUB
from tests.test_metrics_api import OTHER, Env, arm_routes, env

AUTH = {"Authorization": "Bearer " + make_token()}
OTHER_USER = {"Authorization": "Bearer " + make_token(oid="other-oid")}
CSV_CHECKS = {"format": "csv", "family": "AzureWindowsBaseline"}


def create(e: Env, body: dict[str, Any], headers: dict[str, str] = AUTH) -> Any:
    return e.client.post("/api/v1/exports", json=body, headers=headers)


def events(e: Env) -> list[str]:
    with e.factory() as s:
        return [r.event for r in s.scalars(select(ExportAuditRow).order_by(ExportAuditRow.id))]


def add_hidden_machine(e: Env, name: str = "hidden-vm") -> None:
    mid = (
        f"/subscriptions/{OTHER}/resourceGroups/rg/providers/"
        f"Microsoft.Compute/virtualMachines/{name}"
    )
    with e.factory() as s:
        first = s.scalars(select(MachineRow)).first()
        snap = s.scalars(
            select(MetricSnapshotRow).where(MetricSnapshotRow.family == "AzureWindowsBaseline")
        ).first()
        assert first is not None and snap is not None
        s.add(
            MachineRow(
                machine_id=mid,
                name=name,
                kind="AzureVM",
                subscription_id=OTHER,
                resource_group="rg",
                os_type="Windows",
                eligibility="Eligible",
                last_seen_at=first.last_seen_at,
            )
        )
        s.add(
            MachineStatusSnapshotRow(
                snapshot_id=snap.id,
                machine_id=mid,
                family=snap.family,
                evidence_quality="Fresh",
                reported_state="Compliant",
                green=True,
            )
        )
        s.commit()


def test_endpoints_require_bearer() -> None:
    e = env()
    assert e.client.post("/api/v1/exports", json=CSV_CHECKS).status_code == 401
    assert e.client.get("/api/v1/exports").status_code == 401
    assert e.client.get("/api/v1/exports/x/download").status_code == 401


def test_csv_checks_matches_ui_grain_and_has_disclosures() -> None:
    e = env()
    r = create(e, CSV_CHECKS)
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "completed" and job["snapshotAt"]
    d = e.client.get(f"/api/v1/exports/{job['jobId']}/download", headers=AUTH)
    assert d.status_code == 200
    assert d.headers["cache-control"] == "no-store"
    assert "attachment" in d.headers["content-disposition"]
    text = d.content.decode("utf-8-sig")
    for needle in ("Scope:", "Snapshot:", "Freshness:", "synthetic", "certification"):
        assert needle in text
    ui = 0
    for c in e.client.get(
        "/api/v1/metrics/categories?family=AzureWindowsBaseline", headers=AUTH
    ).json()["categories"]:
        ui += c["checks"]
    assert job["rowCount"] == ui and ui > 0
    assert events(e) == ["export.created", "export.downloaded"]


def test_machines_csv_does_not_leak_other_scopes() -> None:
    e = env()
    e.register(OTHER)
    add_hidden_machine(e)
    r = create(e, {"format": "csv", "family": "AzureWindowsBaseline", "dataset": "machines"})
    assert r.status_code == 201
    body = e.client.get(f"/api/v1/exports/{r.json()['jobId']}/download", headers=AUTH).text
    assert "hidden-vm" not in body and OTHER not in body
    assert "Partial" in body


def test_pdf_does_not_leak_or_claim_certification() -> None:
    e = env()
    e.register(OTHER)
    add_hidden_machine(e)
    for template in ("executive", "technical"):
        r = create(e, {"format": "pdf", "family": "AzureWindowsBaseline", "template": template})
        assert r.status_code == 201
        d = e.client.get(f"/api/v1/exports/{r.json()['jobId']}/download", headers=AUTH)
        assert d.headers["content-type"] == "application/pdf"
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(d.content)).pages)
        assert "hidden-vm" not in text and OTHER not in text
        assert "not a CIS, ISO, NIS2 or DORA certification" in text
        assert "synthetic" in text and "Snapshot:" in text


def test_explicit_unauthorized_scope_filter_denied_and_audited() -> None:
    e = env()
    e.register(OTHER)
    r = create(e, {**CSV_CHECKS, "subscriptionId": OTHER})
    assert r.status_code == 403
    assert events(e) == ["export.denied"]


def test_create_fails_closed_when_azure_access_unverifiable() -> None:
    e = env()
    e.obo_fail = True
    assert create(e, CSV_CHECKS).status_code == 403
    e2 = env()
    e2.arm = FakeArm(arm_routes(readable=(OTHER,)))
    e2.app.dependency_overrides[deps.get_arm] = lambda: e2.arm
    assert create(e2, CSV_CHECKS).status_code == 403


def test_download_reauthorizes_on_revoked_access() -> None:
    e = env()
    job = create(e, CSV_CHECKS).json()
    url = f"/api/v1/exports/{job['jobId']}/download"
    e.obo_fail = True
    assert e.client.get(url, headers=AUTH).status_code == 403
    e.obo_fail = False
    e.arm = FakeArm(arm_routes(readable=(OTHER,)))
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    assert e.client.get(url, headers=AUTH).status_code == 403
    e.arm = FakeArm(arm_routes())
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    assert e.client.get(url, headers=AUTH).status_code == 200


def test_download_denied_when_scope_set_shrinks() -> None:
    e = env()
    e.register(OTHER)
    e.arm = FakeArm(arm_routes(readable=(SUB, OTHER)))
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    job = create(e, CSV_CHECKS).json()
    e.arm = FakeArm(arm_routes(readable=(SUB,)))
    e.app.dependency_overrides[deps.get_arm] = lambda: e.arm
    r = e.client.get(f"/api/v1/exports/{job['jobId']}/download", headers=AUTH)
    assert r.status_code == 403
    assert "export.denied" in events(e)


def test_other_user_cannot_see_or_download() -> None:
    e = env()
    job = create(e, CSV_CHECKS).json()
    base = f"/api/v1/exports/{job['jobId']}"
    assert e.client.get(base, headers=OTHER_USER).status_code == 404
    assert e.client.get(base + "/download", headers=OTHER_USER).status_code == 404
    assert e.client.get("/api/v1/exports", headers=OTHER_USER).json() == {"jobs": []}


def test_expiry_purges_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    e = env()
    job = create(e, CSV_CHECKS).json()
    later = _now() + exports.ARTIFACT_TTL + timedelta(seconds=1)
    monkeypatch.setattr(exports, "_now", lambda: later)
    r = e.client.get(f"/api/v1/exports/{job['jobId']}/download", headers=AUTH)
    assert r.status_code == 410
    with e.factory() as s:
        row = s.get(ExportJobRow, job["jobId"])
        assert row is not None and row.artifact is None and row.status == "expired"
    assert (
        e.client.get(f"/api/v1/exports/{job['jobId']}", headers=AUTH).json()["status"] == "expired"
    )
    assert "export.purged" in events(e) and "export.expired" in events(e)


def test_purge_deletes_old_tombstones() -> None:
    e = env()
    job = create(e, CSV_CHECKS).json()
    with e.factory() as s:
        assert exports.purge_expired(s, _now() + timedelta(days=2)) == 1
        assert s.get(ExportJobRow, job["jobId"]) is None


def test_active_jobs_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    e = env()
    monkeypatch.setattr(exports, "MAX_ACTIVE_JOBS_PER_USER", 2)
    assert create(e, CSV_CHECKS).status_code == 201
    assert create(e, CSV_CHECKS).status_code == 201
    assert create(e, CSV_CHECKS).status_code == 429


def test_oversize_export_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    e = env()
    monkeypatch.setattr(exports, "MAX_ARTIFACT_BYTES", 10)
    assert create(e, CSV_CHECKS).status_code == 413


def test_row_limit_truncates_and_discloses(monkeypatch: pytest.MonkeyPatch) -> None:
    e = env()
    monkeypatch.setattr(exports, "MAX_ROWS", 3)
    job = create(e, CSV_CHECKS).json()
    assert job["truncated"] is True and job["rowCount"] == 3
    body = e.client.get(f"/api/v1/exports/{job['jobId']}/download", headers=AUTH).text
    assert "Truncated at 3 rows" in body


def test_invalid_request_rejected() -> None:
    e = env()
    assert create(e, {"format": "xlsx", "family": "AzureWindowsBaseline"}).status_code == 422
    assert create(e, {**CSV_CHECKS, "extra": 1}).status_code == 422


def test_formula_injection_in_stored_names_is_neutralized() -> None:
    e = env()
    with e.factory() as s:
        for m in s.scalars(select(MachineRow)):
            m.name = '=HYPERLINK("http://evil.example","x")'
        s.commit()
    r = create(e, {"format": "csv", "family": "AzureWindowsBaseline", "dataset": "machines"})
    body = e.client.get(f"/api/v1/exports/{r.json()['jobId']}/download", headers=AUTH).text
    cells = [c for line in body.splitlines() for c in line.split(",")]
    assert not any(re.match(r'^"?[=+\-@]', c) for c in cells if "HYPERLINK" in c)
    assert "'=HYPERLINK" in body


@pytest.mark.parametrize("v", ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tx", "\rx", "|calc", "%x"])
def test_csv_cell_prefixes_dangerous_text(v: str) -> None:
    assert csv_cell(v).startswith("'")


def test_csv_cell_leaves_numbers_and_safe_text() -> None:
    assert csv_cell(-5) == -5 and csv_cell(None) == "" and csv_cell("ok") == "ok"
    assert csv_cell("a\x00b") == "ab"


def test_build_csv_sanitizes_preamble_and_cells() -> None:
    out = build_csv(["=evil"], ["h"], [["@x"], [3]]).decode("utf-8-sig")
    assert "'=evil" in out and "'@x" in out and "\n3" in out.replace("\r\n", "\n")


def test_pdf_escapes_content_and_has_no_remote_assets() -> None:
    doc = PdfDoc()
    nasty = r"a) Tj ET /U R I (http://evil.example) \ ( unbalanced \u202e é€ " + "x" * 300
    doc.add("p", nasty)
    pdf = doc.render()
    reader = PdfReader(io.BytesIO(pdf))
    assert "evil.example" in reader.pages[0].extract_text()
    for forbidden in (
        b"/URI",
        b"/Annots",
        b"/JavaScript",
        b"/Launch",
        b"/XObject",
        b"/EmbeddedFile",
    ):
        assert forbidden not in pdf.replace(b"\\(http://evil.example\\)", b"")
    assert pdf_text("a\x00b\u20ac") == "ab?"


def test_pdf_paginates() -> None:
    doc = PdfDoc()
    for i in range(300):
        doc.add("p", f"line {i}")
    assert len(PdfReader(io.BytesIO(doc.render())).pages) > 3
