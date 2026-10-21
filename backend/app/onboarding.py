"""Onboarding scope registration, persisted in the ``onboarded_scopes`` table."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_onboarding import OnboardedScopeRow


@dataclass(frozen=True)
class RegisteredScope:
    subscription_id: str
    registered_by: str
    registered_at: datetime


def _scope(row: OnboardedScopeRow) -> RegisteredScope:
    at = row.registered_at
    return RegisteredScope(
        row.subscription_id, row.registered_by, at if at.tzinfo else at.replace(tzinfo=UTC)
    )


class OnboardingStore:
    """Idempotent registry; the first registration of a subscription wins."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def register(self, subscription_id: str, registered_by: str) -> RegisteredScope:
        sid = subscription_id.lower()
        existing = self._session.get(OnboardedScopeRow, sid)
        if existing is None:
            self._session.add(
                OnboardedScopeRow(
                    subscription_id=sid,
                    registered_by=registered_by,
                    registered_at=datetime.now(UTC),
                )
            )
            try:
                self._session.commit()
            except IntegrityError:  # concurrent registration of the same scope
                self._session.rollback()
            existing = self._session.get(OnboardedScopeRow, sid)
        assert existing is not None
        return _scope(existing)

    def list(self) -> list[RegisteredScope]:
        rows = self._session.scalars(
            select(OnboardedScopeRow).order_by(OnboardedScopeRow.subscription_id)
        )
        return [_scope(r) for r in rows]


PLACEHOLDER_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


def seed_configured_scopes(session: Session, subscription_ids: list[str]) -> list[str]:
    """Register operator-configured subscriptions (ACD_SUBSCRIPTION_IDS) as onboarded scopes.

    Idempotent; existing registrations are untouched. Viewers still need Azure RBAC read access
    to a scope before they see any of its data.
    """
    store = OnboardingStore(session)
    seeded = []
    for sid in subscription_ids:
        if sid.lower() == PLACEHOLDER_SUBSCRIPTION:
            continue
        store.register(sid, "config")
        seeded.append(sid.lower())
    return seeded
