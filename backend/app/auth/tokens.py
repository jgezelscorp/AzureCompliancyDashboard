"""Validation of Entra ID access tokens issued for this API."""

from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from app.auth.settings import AuthSettings


class TokenError(Exception):
    """Token rejected. The message is safe to log but not to echo to clients."""


class SigningKeyProvider(Protocol):
    def get_signing_key(self, token: str) -> Any: ...


class JwksSigningKeyProvider:
    """Fetches and caches Entra signing keys (network; not used in unit tests)."""

    def __init__(self, jwks_uri: str) -> None:
        self._client = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)

    def get_signing_key(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


@dataclass(frozen=True)
class Principal:
    object_id: str
    tenant_id: str
    name: str | None
    scopes: frozenset[str]
    token: str = ""


class TokenValidator:
    def __init__(self, settings: AuthSettings, keys: SigningKeyProvider) -> None:
        self._s = settings
        self._keys = keys

    def validate(self, token: str) -> Principal:
        try:
            key = self._keys.get_signing_key(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=["RS256"],  # explicit allowlist; never "none"/HS*
                audience=self._s.audiences,
                issuer=self._s.issuer,
                leeway=self._s.clock_skew_seconds,
                options={"require": ["exp", "iss", "aud", "tid", "oid"]},
            )
        except Exception as exc:  # any failure rejects, including key-fetch errors
            raise TokenError(f"token rejected: {type(exc).__name__}") from exc
        if str(claims.get("tid", "")).lower() != self._s.tenant_id:
            raise TokenError("token rejected: tenant mismatch")
        scopes = frozenset(str(claims.get("scp", "")).split())
        if self._s.required_scope not in scopes:
            raise TokenError("token rejected: missing delegated scope")
        name = claims.get("name")
        return Principal(
            object_id=str(claims["oid"]),
            tenant_id=self._s.tenant_id,
            name=name if isinstance(name, str) else None,
            scopes=scopes,
            token=token,
        )
