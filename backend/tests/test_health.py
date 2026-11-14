from httpx import ASGITransport, AsyncClient

from app import __version__
from app.core.config import Settings, get_settings
from app.main import app


async def test_health_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["env"] == get_settings().app_env


async def test_health_reports_configured_env() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="test")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["env"] == "test"
