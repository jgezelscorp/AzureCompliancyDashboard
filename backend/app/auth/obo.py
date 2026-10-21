"""On-behalf-of (OBO) exchange: API token -> delegated ARM token for the viewer."""

import httpx

from app.auth.settings import AuthSettings


class OboError(Exception):
    """OBO exchange failed. Callers must fail closed."""


class OboClient:
    def __init__(self, settings: AuthSettings, http: httpx.Client | None = None) -> None:
        self._s = settings
        self._http = http or httpx.Client(timeout=10.0)

    def exchange(self, user_token: str) -> str:
        secret = self._s.api_client_secret
        if secret is None:
            raise OboError("OBO client credential is not configured")
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "client_id": self._s.api_client_id,
            "client_secret": secret.get_secret_value(),
            "assertion": user_token,
            "scope": self._s.arm_scope,
            "requested_token_use": "on_behalf_of",
        }
        try:
            resp = self._http.post(self._s.token_endpoint, data=data)
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OboError(f"OBO request failed: {type(exc).__name__}") from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        if resp.status_code != 200 or not isinstance(token, str) or not token:
            raise OboError(f"OBO exchange rejected (status {resp.status_code})")
        return token
