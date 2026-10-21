import json
import time
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import arm as arm_mod
from app.arm import ArmError, HttpArmClient, validate_next_link
from app.auth import deps, permissions
from app.auth.obo import OboClient, OboError
from app.auth.permissions import (
    CONFIG_EDIT_ACTION,
    PERMISSIONS_API_VERSION,
    VIEWER_READ_ACTIONS,
    PermissionError_,
    has_action,
    is_action_allowed,
)
from app.auth.settings import AuthSettings, get_auth_settings
from app.auth.tokens import TokenError, TokenValidator
from app.config import Settings
from app.main import create_app
from app.onboarding import OnboardingStore
from tests.sqlite_compat import make_session_factory

TENANT = "11111111-1111-1111-1111-111111111111"
API = "22222222-2222-2222-2222-222222222222"
ANCHOR_SUB = "33333333-3333-3333-3333-333333333333"
SUB_A = "44444444-4444-4444-4444-444444444444"
SUB_B = "55555555-5555-5555-5555-555555555555"
ROOT = Path(__file__).resolve().parents[2]

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def settings(**kw: Any) -> AuthSettings:
    base: dict[str, Any] = {
        "tenant_id": TENANT,
        "api_client_id": API,
        "api_client_secret": SecretStr("synthetic-not-a-secret"),
        "anchor_subscription_id": ANCHOR_SUB,
        "anchor_resource_group": "rg-anchor",
    }
    return AuthSettings(**(base | kw))


def make_token(key: Any = KEY, **over: Any) -> str:
    claims: dict[str, Any] = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": API,
        "tid": TENANT,
        "oid": "user-oid",
        "name": "Synthetic User",
        "scp": "access_as_user",
        "exp": int(time.time()) + 600,
    }
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


class FakeKeys:
    def get_signing_key(self, token: str) -> Any:
        return KEY.public_key()


class FakeArm:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, token: str, api_version: str) -> dict[str, Any]:
        return self.get_all(path, token, api_version)[0]

    def get_all(self, path: str, token: str, api_version: str) -> list[dict[str, Any]]:
        self.calls.append(("GET", path))
        r = self.routes.get(path)
        if r is None or isinstance(r, Exception):
            raise r or ArmError("not found")
        return r  # type: ignore[no-any-return]


def perm(actions: list[str], not_actions: list[str] | None = None) -> list[dict[str, Any]]:
    return [{"value": [{"actions": actions, "notActions": not_actions or []}]}]


ANCHOR_PATH = (
    f"/subscriptions/{ANCHOR_SUB}/resourcegroups/rg-anchor"
    "/providers/Microsoft.Authorization/permissions"
)


def sub_path(sid: str) -> str:
    return f"/subscriptions/{sid}/providers/Microsoft.Authorization/permissions"


# ---- token validation -------------------------------------------------------------
def validator() -> TokenValidator:
    return TokenValidator(settings(), FakeKeys())


def test_valid_token() -> None:
    p = validator().validate(make_token())
    assert p.object_id == "user-oid" and "access_as_user" in p.scopes


@pytest.mark.parametrize(
    "over",
    [
        {"exp": int(time.time()) - 3600},
        {"aud": "other"},
        {"iss": "https://evil.example/v2.0"},
        {"tid": "99999999-9999-9999-9999-999999999999"},
        {"scp": "other"},
        {"scp": None},
        {"oid": None},
    ],
)
def test_invalid_claims_rejected(over: dict[str, Any]) -> None:
    with pytest.raises(TokenError):
        validator().validate(make_token(**over))


def test_bad_signature_and_garbage_rejected() -> None:
    with pytest.raises(TokenError):
        validator().validate(make_token(key=OTHER_KEY))
    with pytest.raises(TokenError):
        validator().validate("not-a-jwt")


def test_alg_none_rejected() -> None:
    unsigned = jwt.encode({"aud": API}, "", algorithm="none")
    with pytest.raises(TokenError):
        validator().validate(unsigned)


# ---- OBO ---------------------------------------------------------------------------
def obo_client(handler: Any, **kw: Any) -> OboClient:
    return OboClient(settings(**kw), httpx.Client(transport=httpx.MockTransport(handler)))


def test_obo_success_sends_expected_form() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={"access_token": "arm-token"})

    assert obo_client(handler).exchange("user-jwt") == "arm-token"
    assert seen["url"].endswith(f"/{TENANT}/oauth2/v2.0/token")
    assert "requested_token_use=on_behalf_of" in seen["body"]
    assert "management.azure.com" in seen["body"]


def test_obo_failures_raise() -> None:
    with pytest.raises(OboError):
        obo_client(lambda r: httpx.Response(400, json={"error": "invalid_grant"})).exchange("t")
    with pytest.raises(OboError):
        obo_client(lambda r: httpx.Response(200, json={})).exchange("t")
    with pytest.raises(OboError):
        obo_client(lambda r: httpx.Response(200, text="not json")).exchange("t")
    with pytest.raises(OboError):
        obo_client(
            lambda r: httpx.Response(200, json={"access_token": "x"}), api_client_secret=None
        ).exchange("t")


# ---- permissions (fail closed) ------------------------------------------------------
@pytest.mark.parametrize(
    ("actions", "not_actions", "expected"),
    [
        (["*"], [], True),
        (["*"], ["Microsoft.Resources/deployments/write"], False),
        (["*"], ["Microsoft.Authorization/*"], True),
        (["Microsoft.Resources/deployments/*"], [], True),
        (["microsoft.resources/DEPLOYMENTS/write"], [], True),
        (["*/read"], [], False),
        (["Microsoft.Resources/deployments/read"], [], False),
        ([], [], False),
    ],
)
def test_action_semantics(actions: list[str], not_actions: list[str], expected: bool) -> None:
    assert is_action_allowed(perm(actions, not_actions), CONFIG_EDIT_ACTION) is expected


def test_union_across_entries() -> None:
    pages = [
        {"value": [{"actions": ["*"], "notActions": [CONFIG_EDIT_ACTION]}]},
        {"value": [{"actions": ["Microsoft.Resources/deployments/write"], "notActions": []}]},
    ]
    assert is_action_allowed(pages, CONFIG_EDIT_ACTION)


def test_data_actions_are_not_substitutes() -> None:
    pages = [{"value": [{"actions": [], "dataActions": ["*"]}]}]
    assert not is_action_allowed(pages, CONFIG_EDIT_ACTION)


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{}],
        [{"value": "x"}],
        [{"value": [1]}],
        [{"value": [{"actions": "*"}]}],
        [{"value": [{"actions": [1]}]}],
    ],
)
def test_unsupported_shapes_raise(bad: list[dict[str, Any]]) -> None:
    with pytest.raises(PermissionError_):
        is_action_allowed(bad, CONFIG_EDIT_ACTION)


def test_has_action_fails_closed() -> None:
    ok = FakeArm({ANCHOR_PATH: perm(["*"])})
    assert has_action(ok, "t", ANCHOR_SUB, "rg-anchor", CONFIG_EDIT_ACTION)
    err = FakeArm({ANCHOR_PATH: ArmError("boom")})
    assert not has_action(err, "t", ANCHOR_SUB, "rg-anchor", CONFIG_EDIT_ACTION)
    bad_shape = FakeArm({ANCHOR_PATH: [{"value": "nope"}]})
    assert not has_action(bad_shape, "t", ANCHOR_SUB, "rg-anchor", CONFIG_EDIT_ACTION)
    assert not has_action(ok, "t", "not-a-guid", "rg-anchor", CONFIG_EDIT_ACTION)
    assert not has_action(ok, "t", ANCHOR_SUB, "rg/../x", CONFIG_EDIT_ACTION)


# ---- ARM client --------------------------------------------------------------------
def test_next_link_validation() -> None:
    p = "/subscriptions/x/providers/Microsoft.Authorization/permissions"
    good = f"https://management.azure.com{p}?api-version=2022-04-01&$skiptoken=abc"
    assert validate_next_link(good, p, "2022-04-01").startswith(p)
    for bad in [
        f"http://management.azure.com{p}?api-version=2022-04-01",
        f"https://evil.example{p}?api-version=2022-04-01",
        f"https://u:p@management.azure.com{p}?api-version=2022-04-01",
        "https://management.azure.com/other?api-version=2022-04-01",
        f"https://management.azure.com{p}?api-version=2020-01-01",
    ]:
        with pytest.raises(ArmError):
            validate_next_link(bad, p, "2022-04-01")


def test_http_arm_paging_and_failures() -> None:
    p = "/subscriptions/x/providers/Microsoft.Authorization/permissions"
    methods: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        methods.append(req.method)
        assert req.headers["authorization"] == "Bearer tok"
        if "skip" in str(req.url):
            return httpx.Response(200, json={"value": [{"actions": ["b"]}]})
        return httpx.Response(
            200,
            json={
                "value": [{"actions": ["a"]}],
                "nextLink": f"https://management.azure.com{p}?api-version=2022-04-01&skip=1",
            },
        )

    c = HttpArmClient(
        "https://management.azure.com", httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert len(c.get_all(p, "tok", PERMISSIONS_API_VERSION)) == 2
    assert set(methods) == {"GET"}

    c500 = HttpArmClient(
        "https://management.azure.com",
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    with pytest.raises(ArmError):
        c500.get_all(p, "tok", PERMISSIONS_API_VERSION)
    with pytest.raises(ValueError):
        HttpArmClient("https://evil.example")


def test_http_arm_endless_paging_fails() -> None:
    p = "/x"
    link = f"https://management.azure.com{p}?api-version=v"
    c = HttpArmClient(
        "https://management.azure.com",
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"value": [], "nextLink": link})
            )
        ),
    )
    with pytest.raises(ArmError):
        c.get_all(p, "t", "v")


# ---- API / onboarding --------------------------------------------------------------
class FakeObo:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def exchange(self, user_token: str) -> str:
        if self.fail:
            raise OboError("no")
        return "arm-token"


def build(
    routes: dict[str, Any], obo_fail: bool = False
) -> tuple[TestClient, OnboardingStore, FakeArm]:
    app = create_app(Settings(environment="test"))
    store = OnboardingStore(make_session_factory()())
    arm = FakeArm(routes)
    app.dependency_overrides[deps.get_validator] = validator
    app.dependency_overrides[deps.get_obo] = lambda: FakeObo(obo_fail)
    app.dependency_overrides[deps.get_arm] = lambda: arm
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[get_auth_settings] = lambda: settings()
    return TestClient(app), store, arm


def routes(anchor: Any, with_b_readable: bool = False) -> dict[str, Any]:
    full = perm(list(VIEWER_READ_ACTIONS))
    return {
        "/subscriptions": [
            {
                "value": [
                    {"subscriptionId": SUB_A, "displayName": "Synthetic A"},
                    {"subscriptionId": SUB_B, "displayName": "Synthetic B"},
                ]
            }
        ],
        sub_path(SUB_A): full,
        sub_path(SUB_B): full if with_b_readable else perm([VIEWER_READ_ACTIONS[0]]),
        ANCHOR_PATH: anchor,
    }


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def test_auth_required() -> None:
    c, _, _ = build(routes(perm(["*"])))
    assert c.get("/api/v1/auth/me").status_code == 401
    assert c.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert c.get("/api/v1/onboarding/scopes").status_code == 401


def test_public_config_and_me(auth: dict[str, str]) -> None:
    c, _, _ = build({})
    cfg = c.get("/api/v1/auth/config").json()
    assert cfg["apiScope"] == f"api://{API}/access_as_user" and "secret" not in str(cfg).lower()
    assert c.get("/api/v1/auth/me", headers=auth).json()["objectId"] == "user-oid"


def test_capabilities(auth: dict[str, str]) -> None:
    c, _, _ = build(routes(perm(["Microsoft.Resources/deployments/write"])))
    assert c.get("/api/v1/auth/capabilities", headers=auth).json()["canEditSharedConfig"] is True
    c, _, _ = build(routes(perm(["*/read"])))
    assert c.get("/api/v1/auth/capabilities", headers=auth).json()["canEditSharedConfig"] is False
    c, _, _ = build(routes(ArmError("down")))
    assert c.get("/api/v1/auth/capabilities", headers=auth).json()["canEditSharedConfig"] is False


def test_obo_failure_is_403(auth: dict[str, str]) -> None:
    c, _, _ = build(routes(perm(["*"])), obo_fail=True)
    assert c.get("/api/v1/auth/capabilities", headers=auth).status_code == 403
    assert c.get("/api/v1/onboarding/scopes", headers=auth).status_code == 403


def test_list_scopes_per_viewer_readiness(auth: dict[str, str]) -> None:
    c, _, arm = build(routes(perm(["*"])))
    body = {s["subscriptionId"]: s for s in c.get("/api/v1/onboarding/scopes", headers=auth).json()}
    assert body[SUB_A]["readable"] is True
    assert body[SUB_B]["readable"] is False and body[SUB_B]["missingActions"]
    assert all(m == "GET" for m, _ in arm.calls)


def test_register_scope_requires_anchor(auth: dict[str, str]) -> None:
    c, store, _ = build(routes(perm(["*/read"])))
    r = c.post("/api/v1/onboarding/scopes", json={"subscriptionId": SUB_A}, headers=auth)
    assert r.status_code == 403 and store.list() == []
    c, store, _ = build(routes(ArmError("down")))
    assert (
        c.post(
            "/api/v1/onboarding/scopes", json={"subscriptionId": SUB_A}, headers=auth
        ).status_code
        == 403
    )


def test_register_scope_flow(auth: dict[str, str]) -> None:
    c, store, _ = build(routes(perm(["Microsoft.Resources/deployments/write"])))
    ok = c.post("/api/v1/onboarding/scopes", json={"subscriptionId": SUB_A}, headers=auth)
    assert ok.status_code == 201 and ok.json()["registered"] is True
    assert [s.subscription_id for s in store.list()] == [SUB_A]
    assert c.get("/api/v1/onboarding/registered", headers=auth).json() == [SUB_A]
    unreadable = c.post("/api/v1/onboarding/scopes", json={"subscriptionId": SUB_B}, headers=auth)
    assert unreadable.status_code == 422
    invisible = c.post(
        "/api/v1/onboarding/scopes",
        json={"subscriptionId": "66666666-6666-6666-6666-666666666666"},
        headers=auth,
    )
    assert invisible.status_code == 404


def test_anchor_not_configured_denies(auth: dict[str, str]) -> None:
    c, _, _ = build(routes(perm(["*"])))
    app = c.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_auth_settings] = lambda: settings(anchor_resource_group=None)
    r = c.get("/api/v1/auth/capabilities", headers=auth).json()
    assert r == {"canEditSharedConfig": False, "reason": "anchor-not-configured"}


def test_collector_identity_has_no_secret(auth: dict[str, str]) -> None:
    c, _, _ = build({})
    r = c.get("/api/v1/onboarding/collector", headers=auth).json()
    assert r["mode"] == "managed_identity" and set(r) == {"mode", "clientId", "tenantId"}


# ---- permission manifest -------------------------------------------------------------
def load_manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (ROOT / "contracts" / "permissions-manifest.json").read_text("utf-8")
    )
    return data


def test_actions_used_are_in_manifest() -> None:
    m = load_manifest()
    listed = {e["action"] for e in m["viewerReadActions"] + m["configEditActions"]}
    for action in (*VIEWER_READ_ACTIONS, CONFIG_EDIT_ACTION):
        assert action in listed, f"{action} missing from contracts/permissions-manifest.json"
    assert all(
        "verified" in e for e in m["viewerReadActions"] + m["configEditActions"] + m["armEndpoints"]
    )


def test_permissions_endpoint_matches_source_manifest() -> None:
    src = json.loads((ROOT / "contracts" / "source-manifest.json").read_text("utf-8"))
    entry = next(s for s in src["sources"] if s["id"] == "authorization-permissions-rg")
    assert entry["method"] == "GET" and entry["apiVersion"] == PERMISSIONS_API_VERSION
    m = load_manifest()
    for e in m["armEndpoints"]:
        assert e["apiVersion"] in {PERMISSIONS_API_VERSION, permissions.SUBSCRIPTIONS_API_VERSION}


def test_no_write_methods_in_arm_module() -> None:
    assert not any(hasattr(HttpArmClient, n) for n in ("post", "put", "patch", "delete"))
    assert arm_mod.PERMITTED_HOST == "management.azure.com"
