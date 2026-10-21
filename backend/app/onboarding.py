"""Onboarding scope registration (in-memory; persistence is a later work package)."""

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class RegisteredScope:
    subscription_id: str
    registered_by: str
    registered_at: datetime


@dataclass
class OnboardingStore:
    _scopes: dict[str, RegisteredScope] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def register(self, subscription_id: str, registered_by: str) -> RegisteredScope:
        with self._lock:
            existing = self._scopes.get(subscription_id)
            if existing:
                return existing
            scope = RegisteredScope(subscription_id, registered_by, datetime.now(UTC))
            self._scopes[subscription_id] = scope
            return scope

    def list(self) -> list[RegisteredScope]:
        with self._lock:
            return sorted(self._scopes.values(), key=lambda s: s.subscription_id)
