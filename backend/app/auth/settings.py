from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import GUID_RE, PLACEHOLDER_GUID


class AuthSettings(BaseSettings):
    """Entra / OBO / anchor / collector identity configuration (env prefix ACD_AUTH_).

    All identifiers default to placeholders. Secrets come only from the environment.
    """

    model_config = SettingsConfigDict(env_prefix="ACD_AUTH_", env_file=None, extra="ignore")

    authority_host: str = "https://login.microsoftonline.com"
    tenant_id: str = PLACEHOLDER_GUID
    # API app registration (the audience of tokens sent by the SPA).
    api_client_id: str = PLACEHOLDER_GUID
    api_client_secret: SecretStr | None = None
    required_scope: str = "access_as_user"
    # SPA app registration used by the frontend for authorization-code + PKCE.
    spa_client_id: str = PLACEHOLDER_GUID
    arm_scope: str = "https://management.azure.com/.default"
    arm_base_url: str = "https://management.azure.com"
    clock_skew_seconds: int = Field(default=60, ge=0, le=300)
    # Configuration anchor: isolated resource group. Pinned; not editable via the API.
    anchor_subscription_id: str | None = None
    anchor_resource_group: str | None = None

    # Collector identity (config only; the collector never answers viewer authorization).
    collector_mode: Literal["managed_identity", "service_principal", "workload_identity"] = (
        "managed_identity"
    )
    collector_client_id: str | None = None
    collector_tenant_id: str | None = None

    @field_validator(
        "tenant_id",
        "api_client_id",
        "spa_client_id",
        "anchor_subscription_id",
        "collector_client_id",
        "collector_tenant_id",
    )
    @classmethod
    def _guid(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not GUID_RE.match(v):
            raise ValueError("value must be a GUID")
        return v.lower()

    @property
    def issuer(self) -> str:
        return f"{self.authority_host}/{self.tenant_id}/v2.0"

    @property
    def jwks_uri(self) -> str:
        return f"{self.authority_host}/{self.tenant_id}/discovery/v2.0/keys"

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority_host}/{self.tenant_id}/oauth2/v2.0/token"

    @property
    def audiences(self) -> list[str]:
        return [self.api_client_id, f"api://{self.api_client_id}"]

    @property
    def anchor_configured(self) -> bool:
        return bool(self.anchor_subscription_id and self.anchor_resource_group)


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
