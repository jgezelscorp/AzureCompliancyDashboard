import io
import json
import logging
from typing import Any

from fastapi.testclient import TestClient

from app.arm import ArmError
from app.auth import permissions
from app.config import Settings
from app.hardening import RateLimitMiddleware  # noqa: F401
from app.logging_config import JsonFormatter, redact
from app.main import create_app

GUID = "00000000-0000-0000-0000-000000000000"


def test_security_headers_and_request_id(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-request-id"]
    assert "strict-transport-security" not in r.headers


def test_large_responses_are_gzipped(client: TestClient) -> None:
    r = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert r.json()["info"]["title"]


def test_hsts_in_production() -> None:
    s = Settings(
        environment="production",
        tenant_id="11111111-1111-1111-1111-111111111111",
        database_url="postgresql+psycopg://u:pw@h/db",
    )
    assert "strict-transport-security" in TestClient(create_app(s)).get("/healthz").headers


def test_rate_limit_returns_429_but_exempts_health() -> None:
    c = TestClient(create_app(Settings(environment="test", rate_limit_per_minute=3)))
    codes = [c.get("/api/v1/nope").status_code for _ in range(5)]
    assert codes.count(429) == 2
    assert c.get("/healthz").status_code == 200
    limited = c.get("/api/v1/nope")
    assert limited.headers["retry-after"]


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    r = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_readyz_reports_503_without_database() -> None:
    s = Settings(environment="test", database_url="postgresql+psycopg://u:p@127.0.0.1:1/x")
    r = TestClient(create_app(s)).get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"


def test_redaction() -> None:
    parts = ["ey" + "JhbGciOiJSUzI1NiJ9", "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJl"]
    jwt = ".".join(parts)
    out = redact(f"Authorization: Bearer {jwt} password=hunter2 postgresql://acd:s3cr3t@db/x")
    assert jwt not in out and "hunter2" not in out and "s3cr3t" not in out


def test_json_formatter_redacts_extras() -> None:
    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    h.setFormatter(JsonFormatter())
    lg = logging.getLogger("t.redact")
    lg.handlers[:] = [h]
    lg.propagate = False
    lg.warning("token=abc123 failed", extra={"access_token": "xyz", "note": "client_secret=q"})
    rec = json.loads(stream.getvalue())
    assert "abc123" not in stream.getvalue() and "xyz" not in stream.getvalue()
    assert rec["access_token"] == "[REDACTED]"


class CountingArm:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls = 0

    def get_all(self, path: str, token: str, api_version: str) -> list[dict[str, Any]]:
        self.calls += 1
        return self.pages


class FailingArm:
    calls = 0

    def get_all(self, path: str, token: str, api_version: str) -> list[dict[str, Any]]:
        self.calls += 1
        raise ArmError("boom")


def test_permission_cache_hits_and_expires(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    permissions.clear_permission_cache()
    arm = CountingArm([{"value": [{"actions": ["*"], "notActions": []}]}])
    act = "Microsoft.Resources/deployments/write"
    assert permissions.has_action(arm, "tok", GUID, "rg", act)  # type: ignore[arg-type]
    assert permissions.has_action(arm, "tok", GUID, "rg", act)  # type: ignore[arg-type]
    assert arm.calls == 1
    assert permissions.has_action(arm, "other", GUID, "rg", act)  # type: ignore[arg-type]
    assert arm.calls == 2
    monkeypatch.setattr(permissions, "PERMISSION_CACHE_TTL_SECONDS", -1.0)
    permissions.clear_permission_cache()
    permissions.has_action(arm, "tok", GUID, "rg", act)  # type: ignore[arg-type]
    permissions.has_action(arm, "tok", GUID, "rg", act)  # type: ignore[arg-type]
    assert arm.calls == 4
    permissions.clear_permission_cache()


def test_permission_errors_fail_closed_and_are_not_cached() -> None:
    permissions.clear_permission_cache()
    arm = FailingArm()
    assert not permissions.has_action(arm, "tok", GUID, None, "a/b")  # type: ignore[arg-type]
    assert not permissions.has_action(arm, "tok", GUID, None, "a/b")  # type: ignore[arg-type]
    assert arm.calls == 2
