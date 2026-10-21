"""ARM client: allowlist enforcement, retry/backoff with jitter, 429 Retry-After, paging.

The transport is abstract so tests never touch Azure. Credentials are attached only after
the request (or continuation link) passed allowlist validation and are never logged.
"""

import random
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from app.azure.allowlist import (
    PERMITTED_HOST,
    QUERY_PARAMS,
    AllowlistViolation,
    SourceRule,
    match_rule,
    validate_continuation,
)

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
ARM_SCOPE = "https://management.azure.com/.default"


@dataclass(frozen=True)
class ArmRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)
    json: Any = None


@dataclass(frozen=True)
class ArmResponse:
    status: int
    headers: Mapping[str, str]
    body: Any


class TransportError(Exception):
    """Network-level failure (connect, timeout, TLS)."""


class Transport(Protocol):
    def send(self, request: ArmRequest) -> ArmResponse: ...


class TokenProvider(Protocol):
    def get_token(self, scope: str) -> str: ...


class ArmError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"ARM {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class ArmAccessDenied(ArmError):
    pass


class ArmNotFound(ArmError):
    pass


class ArmThrottled(ArmError):
    pass


class ArmServerError(ArmError):
    pass


class ArmSchemaError(ArmError):
    """Response body was not the expected JSON shape."""


class PagingError(Exception):
    """Pagination could not be completed (loop, page cap)."""


def _error_from(resp: ArmResponse) -> ArmError:
    code, message = "Unknown", ""
    if isinstance(resp.body, dict):
        err = resp.body.get("error")
        if isinstance(err, dict):
            code = str(err.get("code", code))
            message = str(err.get("message", ""))[:300]
    cls: type[ArmError]
    if resp.status in (401, 403):
        cls = ArmAccessDenied
    elif resp.status == 404:
        cls = ArmNotFound
    elif resp.status == 429:
        cls = ArmThrottled
    elif resp.status >= 500:
        cls = ArmServerError
    else:
        cls = ArmError
    return cls(resp.status, code, message)


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return float(max(0.0, (when - (now or datetime.now(UTC))).total_seconds()))


class ArmClient:
    def __init__(
        self,
        transport: Transport,
        tokens: TokenProvider,
        *,
        allowed_subscriptions: frozenset[str] | None = None,
        max_retries: int = 5,
        base_delay: float = 0.5,
        max_delay: float = 120.0,
        max_pages: int = 10_000,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self._transport = transport
        self._tokens = tokens
        self._allowed = allowed_subscriptions
        self._max_retries = max_retries
        self._base = base_delay
        self._cap = max_delay
        self._max_pages = max_pages
        self._sleep = sleep
        self._rand = rand

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self._cap)
        return float(min(self._cap, self._base * 2.0**attempt) * (0.5 + self._rand() / 2))

    def _send(self, rule: SourceRule, method: str, url: str, body: Any) -> ArmResponse:
        headers = {
            "Authorization": f"Bearer {self._tokens.get_token(ARM_SCOPE)}",
            "Accept": "application/json",
            "User-Agent": "azure-compliancy-dashboard-collector",
        }
        request = ArmRequest(method, url, headers, body)
        for attempt in range(self._max_retries + 1):
            last = attempt >= self._max_retries
            try:
                resp = self._transport.send(request)
            except TransportError as exc:
                if last:
                    raise ArmServerError(0, "TransportError", str(exc)[:300]) from exc
                self._sleep(self._delay(attempt, None))
                continue
            if 200 <= resp.status < 300:
                return resp
            if resp.status in RETRYABLE_STATUS and not last:
                retry_after = parse_retry_after(
                    {k.lower(): v for k, v in resp.headers.items()}.get("retry-after")
                )
                self._sleep(self._delay(attempt, retry_after))
                continue
            raise _error_from(resp)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def build_url(path: str, api_version: str, params: Mapping[str, str] | None) -> str:
        extra = dict(params or {})
        bad = set(extra) - QUERY_PARAMS
        if bad:
            raise AllowlistViolation(f"query parameters not permitted: {sorted(bad)}")
        query = urlencode({"api-version": api_version, **extra}, quote_via=quote)
        return f"https://{PERMITTED_HOST}{quote(path, safe='/')}?{query}"

    def request(
        self,
        method: str,
        path: str,
        api_version: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Any = None,
    ) -> tuple[SourceRule, dict[str, Any]]:
        rule = match_rule(method, PERMITTED_HOST, path, api_version)
        if rule.method == "POST" and not rule.read_only_query_post:
            raise AllowlistViolation("POST is not a read-only query for this source")
        self._check_scope(path)
        resp = self._send(rule, method.upper(), self.build_url(path, api_version, params), body)
        return rule, _as_object(resp)

    def _check_scope(self, path: str) -> None:
        parts = path.lower().split("/")
        if self._allowed is not None and len(parts) > 2 and parts[1] == "subscriptions":
            if parts[2] not in self._allowed:
                raise AllowlistViolation("subscription is outside the selected scope")

    def get_pages(
        self, path: str, api_version: str, *, params: Mapping[str, str] | None = None
    ) -> Iterator[dict[str, Any]]:
        yield from self._pages("GET", path, api_version, params, None)

    def post_pages(
        self,
        path: str,
        api_version: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Any = None,
    ) -> Iterator[dict[str, Any]]:
        yield from self._pages("POST", path, api_version, params, body)

    def _pages(
        self,
        method: str,
        path: str,
        api_version: str,
        params: Mapping[str, str] | None,
        body: Any,
    ) -> Iterator[dict[str, Any]]:
        rule, page = self.request(method, path, api_version, params=params, body=body)
        seen: set[str] = set()
        for _ in range(self._max_pages):
            yield page
            link = page.get("nextLink") or page.get("@odata.nextLink")
            if not link:
                return
            if not isinstance(link, str) or link in seen:
                raise PagingError("continuation link repeated or malformed")
            seen.add(link)
            safe = validate_continuation(link, rule, self._allowed)
            resp = self._send(rule, method, safe, None)
            page = _as_object(resp)
        raise PagingError("page limit exceeded; result would be incomplete")


def _as_object(resp: ArmResponse) -> dict[str, Any]:
    if not isinstance(resp.body, dict):
        raise ArmSchemaError(resp.status, "MalformedResponse", "expected a JSON object")
    return resp.body


class HttpxTransport:
    """Production transport. Imported lazily so tests need no network stack."""

    def __init__(self, timeout: float = 60.0) -> None:
        import httpx

        self._httpx = httpx
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def send(self, request: ArmRequest) -> ArmResponse:
        try:
            r = self._client.request(
                request.method, request.url, headers=dict(request.headers), json=request.json
            )
        except self._httpx.TransportError as exc:
            raise TransportError(type(exc).__name__) from exc
        try:
            body: Any = r.json() if r.content else {}
        except ValueError:
            body = None
        return ArmResponse(r.status_code, dict(r.headers), body)

    def close(self) -> None:
        self._client.close()


class AzureIdentityTokenProvider:
    """Uses azure-identity (optional extra) with the collector's managed/workload identity."""

    def __init__(self) -> None:
        from azure.identity import DefaultAzureCredential

        self._credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)

    def get_token(self, scope: str) -> str:
        return str(self._credential.get_token(scope).token)


def subscription_of(path: str) -> str | None:
    parts = urlsplit(path).path.lower().split("/")
    return parts[2] if len(parts) > 2 and parts[1] == "subscriptions" else None


def query_params(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
