from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException

from app.arm import ArmClient, ArmError
from app.auth.deps import (
    ArmAccess,
    arm_access,
    can_edit_shared_config,
    current_principal,
    get_arm,
    get_store,
)
from app.auth.permissions import (
    PermissionError_,
    assess_subscription,
    list_visible_subscriptions,
)
from app.auth.settings import AuthSettings, get_auth_settings
from app.auth.tokens import Principal
from app.models import ApiModel
from app.onboarding import OnboardingStore

router = APIRouter(prefix="/api/v1", tags=["auth", "onboarding"])


class AuthConfigResponse(ApiModel):
    authority: str
    tenant_id: str
    spa_client_id: str
    api_scope: str


class MeResponse(ApiModel):
    object_id: str
    name: str | None


class CapabilitiesResponse(ApiModel):
    can_edit_shared_config: bool
    reason: str


class ScopeAccessModel(ApiModel):
    subscription_id: str
    display_name: str | None
    readable: bool
    missing_actions: list[str]
    registered: bool


class CollectorIdentityResponse(ApiModel):
    mode: Literal["managed_identity", "service_principal", "workload_identity"]
    client_id: str | None
    tenant_id: str | None


class RegisterScopeRequest(ApiModel):
    subscription_id: str


Settings_ = Annotated[AuthSettings, Depends(get_auth_settings)]
Arm_ = Annotated[ArmClient, Depends(get_arm)]
Access_ = Annotated[ArmAccess, Depends(arm_access)]
Store_ = Annotated[OnboardingStore, Depends(get_store)]


@router.get("/auth/config", response_model=AuthConfigResponse, response_model_by_alias=True)
def auth_config(s: Settings_) -> AuthConfigResponse:
    """Public, non-secret values the SPA needs for authorization-code + PKCE."""
    return AuthConfigResponse(
        authority=f"{s.authority_host}/{s.tenant_id}",
        tenant_id=s.tenant_id,
        spa_client_id=s.spa_client_id,
        api_scope=f"api://{s.api_client_id}/{s.required_scope}",
    )


@router.get("/auth/me", response_model=MeResponse, response_model_by_alias=True)
def me(principal: Annotated[Principal, Depends(current_principal)]) -> MeResponse:
    return MeResponse(object_id=principal.object_id, name=principal.name)


@router.get("/auth/capabilities", response_model=CapabilitiesResponse, response_model_by_alias=True)
def capabilities(access: Access_, arm: Arm_, s: Settings_) -> CapabilitiesResponse:
    ok, reason = can_edit_shared_config(access, arm, s)
    return CapabilitiesResponse(can_edit_shared_config=ok, reason=reason)


def _visible(access: ArmAccess, arm: ArmClient, store: OnboardingStore) -> list[ScopeAccessModel]:
    try:
        subs = list_visible_subscriptions(arm, access.arm_token)
    except (ArmError, PermissionError_):
        raise HTTPException(502, "Unable to list visible subscriptions") from None
    registered = {r.subscription_id for r in store.list()}
    out: list[ScopeAccessModel] = []
    for sid, name in subs:
        a = assess_subscription(arm, access.arm_token, sid, name)
        out.append(
            ScopeAccessModel(
                subscription_id=sid,
                display_name=name,
                readable=a.readable,
                missing_actions=list(a.missing_actions),
                registered=sid in registered,
            )
        )
    return out


@router.get(
    "/onboarding/scopes", response_model=list[ScopeAccessModel], response_model_by_alias=True
)
def list_scopes(access: Access_, arm: Arm_, store: Store_) -> list[ScopeAccessModel]:
    """Subscriptions the signed-in viewer can see, with per-viewer read readiness."""
    return _visible(access, arm, store)


@router.get("/onboarding/registered", response_model=list[str], response_model_by_alias=True)
def registered_scopes(
    _: Annotated[Principal, Depends(current_principal)], store: Store_
) -> list[str]:
    return [r.subscription_id for r in store.list()]


@router.post(
    "/onboarding/scopes",
    response_model=ScopeAccessModel,
    status_code=201,
    response_model_by_alias=True,
)
def register_scope(
    body: RegisterScopeRequest, access: Access_, arm: Arm_, s: Settings_, store: Store_
) -> ScopeAccessModel:
    """Register an onboarding scope in settings. Requires anchor authorization (fail closed)."""
    ok, _ = can_edit_shared_config(access, arm, s)
    if not ok:
        raise HTTPException(403, "Shared configuration editing is not permitted")
    sid = body.subscription_id.lower()
    match = next((v for v in _visible(access, arm, store) if v.subscription_id == sid), None)
    if match is None:
        raise HTTPException(404, "Subscription is not visible to the caller")
    if not match.readable:
        raise HTTPException(422, "Caller lacks required read access on the subscription")
    store.register(sid, access.principal.object_id)
    return match.model_copy(update={"registered": True})


@router.get(
    "/onboarding/collector",
    response_model=CollectorIdentityResponse,
    response_model_by_alias=True,
)
def collector_identity(
    _: Annotated[Principal, Depends(current_principal)], s: Settings_
) -> CollectorIdentityResponse:
    """Non-secret view of the separate collector identity configuration."""
    return CollectorIdentityResponse(
        mode=s.collector_mode,
        client_id=s.collector_client_id,
        tenant_id=s.collector_tenant_id or s.tenant_id,
    )
