"""Durable onboarded scopes and migration 0003."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.onboarding import OnboardingStore
from tests.sqlite_compat import make_session_factory

SUB = "00000000-0000-0000-0000-000000000000"
ROOT = Path(__file__).resolve().parents[1]


def test_register_is_idempotent_and_first_registrant_wins() -> None:
    factory = make_session_factory()
    with factory() as s:
        first = OnboardingStore(s).register(SUB, "oid-1")
        again = OnboardingStore(s).register(SUB, "oid-2")
        assert first.registered_by == "oid-1" and again.registered_by == "oid-1"
        assert [r.subscription_id for r in OnboardingStore(s).list()] == [SUB]


def test_scopes_survive_a_new_session_and_are_sorted() -> None:
    factory = make_session_factory()
    with factory() as s:
        store = OnboardingStore(s)
        store.register("22222222-2222-2222-2222-222222222222", "oid")
        store.register("11111111-1111-1111-1111-111111111111", "oid")
    with factory() as s:
        listed = OnboardingStore(s).list()
    assert [r.subscription_id[0] for r in listed] == ["1", "2"]
    assert all(r.registered_at.tzinfo is not None for r in listed)


def test_ids_are_normalised_to_lowercase() -> None:
    factory = make_session_factory()
    with factory() as s:
        OnboardingStore(s).register("ABCDEFAB-0000-0000-0000-000000000000", "oid")
        listed = OnboardingStore(s).list()
        assert listed[0].subscription_id == "abcdefab-0000-0000-0000-000000000000"


@pytest.mark.parametrize("revision", ["0002:0003", "base:head"])
def test_migration_0003_sql_generates(revision: str, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, revision, sql=True)
    out = capsys.readouterr().out
    assert "onboarded_scopes" in out


def test_seed_configured_scopes_is_idempotent_and_skips_placeholder() -> None:
    from app.onboarding import seed_configured_scopes

    sub = "11111111-1111-1111-1111-111111111111"
    factory = make_session_factory()
    with factory() as s:
        OnboardingStore(s).register(sub, "oid-1")
        assert seed_configured_scopes(s, [sub.upper(), SUB]) == [sub]
        seed_configured_scopes(s, [sub])
        scopes = OnboardingStore(s).list()
        assert [r.subscription_id for r in scopes] == [sub]
        assert scopes[0].registered_by == "oid-1"
