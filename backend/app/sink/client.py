"""Logs Ingestion API sender: one POST per batch, classified outcomes, no retries of its own.

The caller (outbox drain) owns retry scheduling so that waiting and persistence stay in one
place. Credentials are attached only to requests for the validated ingestion origin and are
never logged. Error bodies are not stored; only an HTTP status and a short error code are kept.
"""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit

from app.azure.client import ArmRequest, TokenProvider, Transport, TransportError, parse_retry_after

INGESTION_SCOPE = "https://monitor.azure.com//.default"
_CODE_RE = re.compile(r"[^A-Za-z0-9_.-]")


class SinkError(Exception):
    def __init__(self, kind: str, status: int = 0, retry_after: float | None = None) -> None:
        super().__init__(f"{kind} (HTTP {status})")
        self.kind = kind
        self.status = status
        self.retry_after = retry_after

    def describe(self) -> str:
        return f"HTTP {self.status} {self.kind}" if self.status else self.kind


class TransientSinkError(SinkError):
    """Worth retrying later: throttling, outage, network or authorization not yet effective."""


class PermanentSinkError(SinkError):
    """The payload (or the stream) was rejected; retrying the same bytes cannot succeed."""


def validate_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not host.endswith(".ingest.monitor.azure.com")
        or parts.username
        or parts.password
        or parts.port
    ):
        raise ValueError("ingestion endpoint must be an https *.ingest.monitor.azure.com origin")
    return f"https://{host}"


def _code(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            return _CODE_RE.sub("", err["code"])[:64] or "Unknown"
    return "Unknown"


class LogsIngestionClient:
    def __init__(
        self,
        transport: Transport,
        tokens: TokenProvider,
        endpoint: str,
        dcr_immutable_id: str,
        api_version: str,
    ) -> None:
        self._transport = transport
        self._tokens = tokens
        self._origin = validate_endpoint(endpoint)
        self._dcr = dcr_immutable_id
        self._api_version = api_version

    def url(self, stream: str) -> str:
        path = f"/dataCollectionRules/{quote(self._dcr, safe='')}/streams/{quote(stream, safe='')}"
        return f"{self._origin}{path}?api-version={self._api_version}"

    def send(self, stream: str, rows: list[dict[str, Any]]) -> None:
        try:
            token = self._tokens.get_token(INGESTION_SCOPE)
        except Exception as exc:  # credential libraries raise many types; none may leak details
            raise TransientSinkError("TokenAcquisitionFailed") from exc
        headers: Mapping[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "azure-compliancy-dashboard-sink",
        }
        try:
            resp = self._transport.send(ArmRequest("POST", self.url(stream), headers, rows))
        except TransportError as exc:
            raise TransientSinkError("TransportError") from exc
        if 200 <= resp.status < 300:
            return
        lowered = {k.lower(): v for k, v in resp.headers.items()}
        retry_after = parse_retry_after(lowered.get("retry-after"))
        code = _code(resp.body)
        if resp.status in (401, 403):
            raise TransientSinkError(f"AccessDenied:{code}", resp.status, retry_after)
        if resp.status in (400, 413):
            raise PermanentSinkError(code, resp.status)
        # Other 4xx (e.g. 404 for a wrong DCR id) are configuration faults an operator can fix.
        raise TransientSinkError(code, resp.status, retry_after)
