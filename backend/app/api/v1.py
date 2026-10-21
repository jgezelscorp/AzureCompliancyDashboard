from typing import Annotated

from fastapi import APIRouter, Depends

from app import __version__
from app.config import Settings, get_settings
from app.models import BundleSummary, EvidenceBundle, InfoResponse

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.get("/info", response_model=InfoResponse, response_model_by_alias=True)
def info(settings: Annotated[Settings, Depends(get_settings)]) -> InfoResponse:
    return InfoResponse(
        version=__version__,
        environment=settings.environment,
        freshness_hours=settings.freshness_hours,
        retention_months=settings.retention_months,
        subscription_count=len(settings.subscription_ids),
    )


@router.post("/evidence/validate", response_model=BundleSummary, response_model_by_alias=True)
def validate_bundle(bundle: EvidenceBundle) -> BundleSummary:
    """Validate an evidence bundle against the typed contract without storing it."""
    return BundleSummary(
        machines=len(bundle.machines),
        assignments=len(bundle.assignments),
        reports=len(bundle.reports),
        checks=sum(len(r.checks) for r in bundle.reports),
        policy_states=len(bundle.policy_states),
        exemptions=len(bundle.exemptions),
        synthetic=bundle.synthetic is True,
    )
