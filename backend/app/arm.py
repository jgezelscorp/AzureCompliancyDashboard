"""Read-only ARM client abstraction. Only GET is exposed; no write calls exist."""

from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx

PERMITTED_HOST = "management.azure.com"


class ArmError(Exception):
    """ARM call failed or returned an unusable response."""


class ArmClient(Protocol):
    def get(self, path: str, token: str, api_version: str) -> dict[str, Any]:
        """GET a single ARM page. `path` starts with '/'."""
        ...

    def get_all(self, path: str, token: str, api_version: str) -> list[dict[str, Any]]:
        """Follow nextLink until exhausted; raise ArmError if paging cannot complete."""
        ...


def validate_next_link(link: str, expected_path: str, api_version: str) -> str:
    """Return the path+query to follow, or raise if the link leaves the allowlist."""
    parts = urlsplit(link)
    if (
        parts.scheme != "https"
        or parts.hostname != PERMITTED_HOST
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise ArmError("nextLink rejected: host/scheme not permitted")
    if parts.path.lower() != expected_path.lower():
        raise ArmError("nextLink rejected: path differs from originating request")
    if parse_qs(parts.query).get("api-version") != [api_version]:
        raise ArmError("nextLink rejected: api-version differs")
    return f"{parts.path}?{parts.query}"


class HttpArmClient:
    MAX_PAGES = 50

    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        if urlsplit(base_url).hostname != PERMITTED_HOST:
            raise ValueError("ARM base URL host is not permitted")
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=15.0)

    def _fetch(self, url: str, token: str, params: dict[str, str] | None) -> dict[str, Any]:
        try:
            resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise ArmError(f"ARM request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ArmError(f"ARM returned status {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ArmError("ARM returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise ArmError("ARM returned unexpected shape")
        return body

    def get(self, path: str, token: str, api_version: str) -> dict[str, Any]:
        return self._fetch(self._base + path, token, {"api-version": api_version})

    def get_all(self, path: str, token: str, api_version: str) -> list[dict[str, Any]]:
        body = self._fetch(self._base + path, token, {"api-version": api_version})
        pages = [body]
        for _ in range(self.MAX_PAGES):
            link = body.get("nextLink")
            if not link:
                return pages
            if not isinstance(link, str):
                raise ArmError("nextLink has unexpected type")
            follow = validate_next_link(link, path, api_version)
            body = self._fetch(self._base + follow, token, None)
            pages.append(body)
        raise ArmError("paging did not complete")
