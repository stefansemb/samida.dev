import httpx
import pytest

from samida.config import Settings, get_settings
from samida.dependencies import get_ollama_provider
from samida.main import app


class FakeOllamaProvider:
    name = "ollama"

    async def model_names(self) -> list[str]:
        return ["gemma4:e4b", "qwen3-vl:8b"]


@pytest.mark.asyncio
async def test_health_reports_configured_model() -> None:
    app.dependency_overrides[get_ollama_provider] = lambda: FakeOllamaProvider()
    app.dependency_overrides[get_settings] = lambda: Settings(openai_api_key=None)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "ollama_reachable": True,
        "configured_model": "gemma4:e4b",
        "model_available": True,
        "configured_vision_model": "qwen3-vl:8b",
        "vision_model_available": True,
        "available_models": ["gemma4:e4b", "qwen3-vl:8b"],
        "openai_configured": False,
    }
