import re
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
DCR_ID_RE = re.compile(r"^dcr-[0-9a-f]{32}$", re.I)
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
    rate_limit_per_minute: int = Field(default=600, ge=0, le=100_000)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    export_purge_interval_minutes: int = Field(default=5, ge=1, le=1440)
    collection_interval_hours: int = Field(default=6, ge=1, le=168)
    collection_concurrency: int = Field(default=4, ge=1, le=16)
    collection_run_timeout_minutes: int = Field(default=180, ge=5)
    arm_max_retries: int = Field(default=5, ge=0, le=10)
    # Optional Log Analytics reporting sink (I08). Off by default; the app never needs it.
    logs_sink_enabled: bool = False
    logs_ingestion_endpoint: str = ""
    logs_dcr_immutable_id: str = ""
    logs_batch_max_bytes: int = Field(default=900_000, ge=10_000, le=1_000_000)
    logs_batch_max_records: int = Field(default=2000, ge=1, le=10_000)
    logs_max_attempts: int = Field(default=12, ge=1, le=100)
    logs_retry_max_minutes: int = Field(default=360, ge=1, le=1440)
    logs_delivered_keep_days: int = Field(default=7, ge=1, le=365)
    logs_max_records_per_drain: int = Field(default=50_000, ge=1)
    # "<policyDefinitionGuidOrId>=<BaselineFamily>,..."; unmapped policy states stay unclassified
    policy_family_map: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    # Repo-managed category overrides: JSON list of {type: exact|prefix|regex, pattern, category}
    category_overrides: str = ""
    category_overrides_file: str = ""
    # Domain overrides: JSON list of {target: policy|check, type, pattern, domain}.
    domain_overrides: str = ""
    domain_overrides_file: str = ""
    # Estate-wide policy view: only these tag keys are stored (tag values may hold personal data).
    estate_tag_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "owner",
            "environment",
            "criticality",
            "costcenter",
            "businessunit",
        ]
    )
    estate_inventory_enabled: bool = True
    defender_enabled: bool = True

    @field_validator("category_overrides")
    @classmethod
    def _overrides_valid(cls, v: str) -> str:
        from app.domain.categories import parse_overrides

        parse_overrides(v)
        return v

    @field_validator("domain_overrides")
    @classmethod
    def _domain_overrides_valid(cls, v: str) -> str:
        from app.domain.domains import parse_domain_overrides

        parse_domain_overrides(v)
        return v

    @field_validator("policy_family_map", mode="before")
    @classmethod
    def _parse_family_map(cls, v: object) -> object:
        if isinstance(v, str):
            pairs = [p.split("=", 1) for p in v.split(",") if "=" in p]
            return {k.strip().lower(): f.strip() for k, f in pairs}
        return v

    @field_validator("policy_family_map")
    @classmethod
    def _family_values(cls, v: dict[str, str]) -> dict[str, str]:
        allowed = {"AzureWindowsBaseline", "CISWindowsSecurityBaseline"}
        if any(f not in allowed for f in v.values()):
            raise ValueError(f"policy_family_map values must be one of {sorted(allowed)}")
        return {k.lower(): f for k, f in v.items()}

    @field_validator("subscription_ids", "cors_origins", "estate_tag_keys", mode="before")
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
    def _logs_sink_requirements(self) -> "Settings":
        if not self.logs_sink_enabled:
            return self
        parts = urlsplit(self.logs_ingestion_endpoint)
        host = (parts.hostname or "").lower()
        if (
            parts.scheme != "https"
            or not host.endswith(".ingest.monitor.azure.com")
            or parts.username
            or parts.password
            or parts.port
            or parts.path not in ("", "/")
        ):
            raise ValueError(
                "logs_ingestion_endpoint must be an https *.ingest.monitor.azure.com origin"
            )
        if not DCR_ID_RE.match(self.logs_dcr_immutable_id):
            raise ValueError("logs_dcr_immutable_id must look like dcr-<32 hex characters>")
        return self

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
