from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.database import get_engine
from app.main import create_app


def test_postgres_engine_fails_fast_when_server_is_unreachable() -> None:
    get_engine.cache_clear()
    engine = get_engine("postgresql+psycopg://u:p@127.0.0.1:5432/db")
    assert engine.pool.timeout() == 5  # type: ignore[attr-defined]
    get_engine.cache_clear()


def test_database_outage_returns_503_and_auth_config_stays_available() -> None:
    app = create_app(Settings(environment="test"))

    def boom() -> dict[str, str]:
        raise OperationalError("SELECT 1", {}, Exception("timeout"))

    app.add_api_route("/_boom", boom, methods=["GET"])
    client = TestClient(app)
    r = client.get("/_boom")
    assert r.status_code == 503
    assert "Database" in r.json()["detail"]
    assert client.get("/api/v1/auth/config").status_code == 200
    assert client.get("/healthz").status_code == 200
