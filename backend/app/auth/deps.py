"""FastAPI dependencies: bearer authentication, OBO and capability checks."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.arm import ArmClient, HttpArmClient
from app.auth.obo import OboClient, OboError
from app.auth.permissions import CONFIG_EDIT_ACTION, has_action
from app.auth.settings import AuthSettings, get_auth_settings
from app.auth.tokens import JwksSigningKeyProvider, Principal, TokenError, TokenValidator
from app.database import get_session
from app.onboarding import OnboardingStore


@lru_cache
def get_validator() -> TokenValidator:
    s = get_auth_settings()
    return TokenValidator(s, JwksSigningKeyProvider(s.jwks_uri))


@lru_cache
def get_obo() -> OboClient:
    return OboClient(get_auth_settings())


@lru_cache
def get_arm() -> ArmClient:
    return HttpArmClient(get_auth_settings().arm_base_url)


def get_store(session: Annotated[Session, Depends(get_session)]) -> OnboardingStore:
    return OnboardingStore(session)


def current_principal(
    validator: Annotated[TokenValidator, Depends(get_validator)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return validator.validate(token)
    except TokenError:
        raise HTTPException(
            401, "Invalid token", headers={"WWW-Authenticate": "Bearer error=invalid_token"}
        ) from None


@dataclass(frozen=True)
class ArmAccess:
    """Delegated ARM token for the current viewer (never the collector's credentials)."""

    principal: Principal
    arm_token: str


def arm_access(
    principal: Annotated[Principal, Depends(current_principal)],
    obo: Annotated[OboClient, Depends(get_obo)],
) -> ArmAccess:
    try:
        return ArmAccess(principal, obo.exchange(principal.token))
    except OboError:
        raise HTTPException(403, "Unable to verify Azure access") from None


def can_edit_shared_config(
    access: ArmAccess, arm: ArmClient, settings: AuthSettings
) -> tuple[bool, str]:
    if not settings.anchor_configured:
        return False, "anchor-not-configured"
    assert settings.anchor_subscription_id is not None
    ok = has_action(
        arm,
        access.arm_token,
        settings.anchor_subscription_id,
        settings.anchor_resource_group,
        CONFIG_EDIT_ACTION,
    )
    return ok, "granted" if ok else "denied-or-unverifiable"
