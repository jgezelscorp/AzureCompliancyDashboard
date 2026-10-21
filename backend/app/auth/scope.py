"""Per-viewer authorized scope set for metrics endpoints (fail closed).

Authorized = onboarded (registered) subscriptions the signed-in viewer can read under Azure RBAC,
decided with the viewer's delegated token. The collector identity never answers this.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException

from app.arm import ArmClient, ArmError
from app.auth.deps import ArmAccess, arm_access, get_arm, get_store
from app.auth.permissions import PermissionError_, assess_subscription, list_visible_subscriptions
from app.auth.tokens import Principal
from app.onboarding import OnboardingStore


@dataclass(frozen=True)
class AuthorizedScopes:
    principal: Principal
    subscription_ids: frozenset[str]
    registered: frozenset[str]

    @property
    def partial(self) -> bool:
        """True when the viewer cannot see every onboarded scope."""
        return not self.registered <= self.subscription_ids


def resolve_scopes(access: ArmAccess, arm: ArmClient, store: OnboardingStore) -> AuthorizedScopes:
    registered = frozenset(r.subscription_id.lower() for r in store.list())
    if not registered:
        return AuthorizedScopes(access.principal, frozenset(), registered)
    try:
        visible = {sid for sid, _ in list_visible_subscriptions(arm, access.arm_token)}
    except (ArmError, PermissionError_):
        raise HTTPException(403, "Unable to verify Azure access") from None
    allowed = frozenset(
        sid
        for sid in registered & visible
        if assess_subscription(arm, access.arm_token, sid, None).readable
    )
    if not allowed:
        raise HTTPException(403, "No authorized scopes")
    return AuthorizedScopes(access.principal, allowed, registered)


def authorized_scopes(
    access: Annotated[ArmAccess, Depends(arm_access)],
    arm: Annotated[ArmClient, Depends(get_arm)],
    store: Annotated[OnboardingStore, Depends(get_store)],
) -> AuthorizedScopes:
    return resolve_scopes(access, arm, store)
