import pytest
from pydantic import ValidationError

from app.config import PLACEHOLDER_GUID, Settings

REAL_LOOKING = "11111111-2222-3333-4444-555555555555"


def test_defaults_are_valid() -> None:
    s = Settings()
    assert s.freshness_hours == 24
    assert s.retention_months == 13
    assert s.tenant_id == PLACEHOLDER_GUID


def test_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACD_SUBSCRIPTION_IDS", f"{REAL_LOOKING}, {PLACEHOLDER_GUID}")
    monkeypatch.setenv("ACD_FRESHNESS_HOURS", "48")
    s = Settings()
    assert s.subscription_ids == [REAL_LOOKING, PLACEHOLDER_GUID]
    assert s.freshness_hours == 48


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_id": "not-a-guid"},
        {"subscription_ids": ["nope"]},
        {"database_url": "sqlite:///x.db"},
        {"freshness_hours": 0},
        {"retention_months": 0},
        {"environment": "staging"},
    ],
)
def test_invalid_settings_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_production_requires_real_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            tenant_id=REAL_LOOKING,
            database_url="postgresql+psycopg://u:p@db/acd",
            cors_origins=["*"],
        )
    ok = Settings(
        environment="production",
        tenant_id=REAL_LOOKING,
        database_url="postgresql+psycopg://u:p@db/acd",
    )
    assert ok.environment == "production"
