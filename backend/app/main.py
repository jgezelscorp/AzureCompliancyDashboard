from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import router as v1_router
from app.config import Settings, get_settings
from app.models import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    # Settings are validated here, so invalid configuration stops startup.
    settings = settings or get_settings()
    app = FastAPI(title="Azure Compliancy Dashboard API", version=__version__)
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/healthz", response_model=HealthResponse, response_model_by_alias=True)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    app.include_router(v1_router)
    return app


app = create_app()
