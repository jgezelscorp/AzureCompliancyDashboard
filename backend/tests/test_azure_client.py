"""ARM client: allowlist enforcement before credentials, retry/backoff, Retry-After, paging."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from app.azure.allowlist import AllowlistViolation
from app.azure.client import (
    ArmAccessDenied,
    ArmClient,
    ArmNotFound,
    ArmRequest,
    ArmResponse,
    ArmSchemaError,
    ArmServerError,
    ArmThrottled,
    PagingError,
    TransportError,
    parse_retry_after,
)

SUB = "00000000-0000-0000-0000-000000000000"
MACHINE = (
    f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
)
PATH = f"{MACHINE}/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments"
VERSION = "2024-04-05"


class Tokens:
    def __init__(self) -> None:
        self.calls = 0

    def get_token(self, scope: str) -> str:
        self.calls += 1
        return "synthetic-token"


class Script:
    """Replays queued outcomes (responses or exceptions) and records requests."""

    def __init__(self, *outcomes: ArmResponse | Exception) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[ArmRequest] = []

    def send(self, request: ArmRequest) -> ArmResponse:
        self.requests.append(request)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def ok(body: Any = None, status: int = 200) -> ArmResponse:
    return ArmResponse(status, {}, {"value": []} if body is None else body)


def err(status: int, headers: dict[str, str] | None = None) -> ArmResponse:
    return ArmResponse(status, headers or {}, {"error": {"code": "E", "message": "m"}})


def make(
    script: Script,
    sleeps: list[float] | None = None,
    rand: Callable[[], float] = lambda: 1.0,
    **kw: Any,
) -> ArmClient:
    log = sleeps if sleeps is not None else []
    return ArmClient(script, Tokens(), sleep=log.append, rand=rand, **kw)


def test_retries_5xx_with_exponential_backoff_then_succeeds() -> None:
    sleeps: list[float] = []
    script = Script(err(503), err(500), ok())
    _, body = make(script, sleeps, base_delay=1.0).request("GET", PATH, VERSION)
    assert body == {"value": []} and len(script.requests) == 3
    assert sleeps == [1.0, 2.0]  # rand()==1.0 -> full delay


def test_jitter_scales_delay() -> None:
    sleeps: list[float] = []
    make(Script(err(503), ok()), sleeps, rand=lambda: 0.0, base_delay=2.0).request(
        "GET", PATH, VERSION
    )
    assert sleeps == [1.0]


def test_429_honours_retry_after_seconds_capped() -> None:
    sleeps: list[float] = []
    script = Script(err(429, {"Retry-After": "7"}), err(429, {"retry-after": "9999"}), ok())
    make(script, sleeps, max_delay=30.0).request("GET", PATH, VERSION)
    assert sleeps == [7.0, 30.0]


def test_gives_up_after_max_retries() -> None:
    script = Script(*[err(503)] * 3)
    with pytest.raises(ArmServerError):
        make(script, max_retries=2).request("GET", PATH, VERSION)
    assert len(script.requests) == 3


def test_throttling_exhausted_raises_throttled() -> None:
    with pytest.raises(ArmThrottled):
        make(Script(err(429), err(429)), max_retries=1).request("GET", PATH, VERSION)


@pytest.mark.parametrize(
    ("status", "exc"), [(401, ArmAccessDenied), (403, ArmAccessDenied), (404, ArmNotFound)]
)
def test_non_retryable_errors_fail_immediately(status: int, exc: type[Exception]) -> None:
    script = Script(err(status), ok())
    with pytest.raises(exc):
        make(script).request("GET", PATH, VERSION)
    assert len(script.requests) == 1


def test_transport_errors_are_retried_then_wrapped() -> None:
    assert make(Script(TransportError("x"), ok())).request("GET", PATH, VERSION)
    with pytest.raises(ArmServerError):
        make(Script(TransportError("a"), TransportError("b")), max_retries=1).request(
            "GET", PATH, VERSION
        )


def test_malformed_body_is_schema_error() -> None:
    with pytest.raises(ArmSchemaError):
        make(Script(ArmResponse(200, {}, ["not", "an", "object"]))).request("GET", PATH, VERSION)


def test_error_message_truncated_and_no_token_leak() -> None:
    long = ArmResponse(500, {}, {"error": {"code": "E", "message": "x" * 1000}})
    with pytest.raises(ArmServerError) as exc:
        make(Script(long), max_retries=0).request("GET", PATH, VERSION)
    assert len(exc.value.message) == 300 and "synthetic-token" not in str(exc.value)


def test_disallowed_requests_never_reach_transport_or_token_provider() -> None:
    script, tokens = Script(), Tokens()
    client = ArmClient(script, tokens, sleep=lambda _s: None)
    for method, path, version in [
        ("PUT", PATH, VERSION),
        ("GET", PATH, "2000-01-01"),
        ("POST", PATH, VERSION),
        ("GET", "/subscriptions/x/resourceGroups/rg", VERSION),
    ]:
        with pytest.raises(AllowlistViolation):
            client.request(method, path, version)
    assert script.requests == [] and tokens.calls == 0


def test_subscription_scope_enforced() -> None:
    script = Script(ok())
    client = make(script, allowed_subscriptions=frozenset(["22222222-2222-2222-2222-222222222222"]))
    with pytest.raises(AllowlistViolation):
        client.request("GET", PATH, VERSION)
    assert script.requests == []


def test_unpermitted_query_parameters_rejected() -> None:
    with pytest.raises(AllowlistViolation):
        make(Script()).request("GET", PATH, VERSION, params={"evil": "1"})


def test_authorization_header_attached_and_hidden_from_repr() -> None:
    script = Script(ok())
    make(script).request("GET", PATH, VERSION)
    req = script.requests[0]
    assert req.headers["Authorization"].startswith("Bearer ")
    assert "Bearer" not in repr(req)
    assert req.url.startswith("https://management.azure.com/") and "api-version=" in req.url


def test_paging_follows_validated_links() -> None:
    nxt = f"https://management.azure.com{PATH}?api-version={VERSION}&$skiptoken=2"
    script = Script(ok({"value": [1], "nextLink": nxt}), ok({"value": [2]}))
    pages = list(make(script).get_pages(PATH, VERSION))
    assert [p["value"] for p in pages] == [[1], [2]]
    assert script.requests[1].url == nxt


def test_paging_rejects_malicious_and_repeated_links() -> None:
    evil = f"https://evil.example{PATH}?api-version={VERSION}"
    script = Script(ok({"value": [], "nextLink": evil}))
    with pytest.raises(AllowlistViolation):
        list(make(script).get_pages(PATH, VERSION))
    assert len(script.requests) == 1  # credentials were never sent to the evil host

    loop = f"https://management.azure.com{PATH}?api-version={VERSION}&$skiptoken=1"
    looping = Script(ok({"nextLink": loop}), ok({"nextLink": loop}), ok({"nextLink": loop}))
    with pytest.raises(PagingError):
        list(make(looping).get_pages(PATH, VERSION))


def test_page_cap_prevents_silently_incomplete_results() -> None:
    def page(i: int) -> ArmResponse:
        link = f"https://management.azure.com{PATH}?api-version={VERSION}&$skiptoken={i}"
        return ok({"nextLink": link})

    with pytest.raises(PagingError):
        list(make(Script(*[page(i) for i in range(5)]), max_pages=3).get_pages(PATH, VERSION))


def test_post_query_pages_use_body() -> None:
    script = Script(ok({"data": []}))
    body = {"query": "Resources | take 1"}
    pages = list(
        make(script).post_pages(
            "/providers/Microsoft.ResourceGraph/resources", "2024-04-01", body=body
        )
    )
    assert pages and script.requests[0].method == "POST" and script.requests[0].json == body


def test_parse_retry_after() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after(" 12 ") == 12.0
    assert parse_retry_after("Thu, 01 Jan 2026 12:00:30 GMT", now) == 30.0
    assert parse_retry_after("Thu, 01 Jan 2026 11:00:00 GMT", now) == 0.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None and parse_retry_after("") is None
