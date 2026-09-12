from pathlib import Path

import httpx
import pytest

from samida import rate_limit
from samida.config import Settings, get_settings
from samida.dependencies import get_conversation_store
from samida.main import app
from samida.storage import ConversationStore


@pytest.mark.asyncio
async def test_register_endpoint_is_rate_limited_per_ip(tmp_path: Path, monkeypatch) -> None:
    # Fresh limiter instances so this test can't be polluted by, or pollute,
    # any other test that happens to hit the app through the same client IP.
    monkeypatch.setattr(rate_limit, "register_limiter", rate_limit.RateLimiter(max_requests=5, window_seconds=3600))
    monkeypatch.setattr(rate_limit, "global_limiter", rate_limit.RateLimiter(max_requests=1000, window_seconds=60))

    store = ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(cookie_secure=False)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for i in range(5):
                response = await client.post(
                    "/api/auth/register", json={"email": f"user{i}@example.com", "password": "hunter2hunter2"}
                )
                assert response.status_code == 201

            blocked = await client.post(
                "/api/auth/register", json={"email": "one-too-many@example.com", "password": "hunter2hunter2"}
            )
    finally:
        app.dependency_overrides.clear()

    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_login_endpoint_is_rate_limited_per_ip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "login_limiter", rate_limit.RateLimiter(max_requests=10, window_seconds=60))
    monkeypatch.setattr(rate_limit, "global_limiter", rate_limit.RateLimiter(max_requests=1000, window_seconds=60))

    store = ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(cookie_secure=False)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(10):
                response = await client.post(
                    "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
                )
                assert response.status_code == 401  # wrong credentials, but not rate limited yet

            blocked = await client.post(
                "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
            )
    finally:
        app.dependency_overrides.clear()

    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_global_rate_limit_returns_429_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "global_limiter", rate_limit.RateLimiter(max_requests=2, window_seconds=60))

    store = ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")
    app.dependency_overrides[get_conversation_store] = lambda: store
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/auth/me")
            await client.get("/api/auth/me")
            blocked = await client.get("/api/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert blocked.status_code == 429
    assert "Too many requests" in blocked.json()["detail"]
