from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.api.exports import router as exports_router
from app.api.metrics import router as metrics_router
from app.api.v1 import router as v1_router
from app.api.v1_auth import router as auth_router
from app.config import Settings, get_settings
from app.database import get_engine
from app.hardening import RateLimitMiddleware, SecurityHeadersMiddleware
from app.logging_config import configure_logging
from app.models import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    # Settings are validated here, so invalid configuration stops startup.
    settings = settings or get_settings()
    if settings.environment != "test":
        configure_logging(settings.log_level)
    app = FastAPI(title="Azure Compliancy Dashboard API", version=__version__)
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "production")

    @app.get("/healthz", response_model=HealthResponse, response_model_by_alias=True)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str]:
        try:
            with get_engine(settings.database_url).connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            response.status_code = 503
            return {"status": "unavailable", "database": "down"}
        return {"status": "ready", "database": "ok"}

    app.include_router(v1_router)
    app.include_router(auth_router)
    app.include_router(metrics_router)
    app.include_router(exports_router)
    return app


app = create_app()
