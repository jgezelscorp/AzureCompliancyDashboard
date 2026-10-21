import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
PLACEHOLDER_GUID = "00000000-0000-0000-0000-000000000000"


class Settings(BaseSettings):
    """Runtime configuration. Validated at startup; fails fast on invalid values.

    Tenant and subscription IDs are configuration only and are never hardcoded.
    """

    model_config = SettingsConfigDict(env_prefix="ACD_", env_file=None, extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://acd:change-me@localhost:5432/acd"
    tenant_id: str = PLACEHOLDER_GUID
    subscription_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    freshness_hours: int = Field(default=24, ge=1, le=168)
    retention_months: int = Field(default=13, ge=1, le=60)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @field_validator("subscription_ids", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("tenant_id")
    @classmethod
    def _tenant_guid(cls, v: str) -> str:
        if not GUID_RE.match(v):
            raise ValueError("tenant_id must be a GUID")
        return v.lower()

    @field_validator("subscription_ids")
    @classmethod
    def _subscription_guids(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if not GUID_RE.match(s)]
        if bad:
            raise ValueError("subscription_ids must all be GUIDs")
        return [s.lower() for s in v]

    @field_validator("database_url")
    @classmethod
    def _database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("database_url must be a PostgreSQL URL")
        return v

    @model_validator(mode="after")
    def _production_requirements(self) -> "Settings":
        if self.environment == "production":
            if self.tenant_id == PLACEHOLDER_GUID:
                raise ValueError("tenant_id must be configured in production")
            if "change-me" in self.database_url:
                raise ValueError("database_url must not use the placeholder password in production")
            if any(o == "*" for o in self.cors_origins):
                raise ValueError("wildcard CORS origin is not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
