import httpx
import pytest

from samida import auth
from samida.config import Settings, get_settings
from samida.main import GENERIC_PRIORITIES_CONTENT, app


OWNER = auth.User(id="owner-1", email="stese2026@gmail.com", tier="full")
GUEST = auth.User(id="guest-1", email="someone-else@example.com", tier="full")


async def _get(path: str, *, user: auth.User) -> httpx.Response:
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[get_settings] = lambda: Settings(owner_email="stese2026@gmail.com")
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_priorities_endpoint_returns_generic_content_for_non_owner() -> None:
    response = await _get("/api/priorities", user=GUEST)
    assert response.json() == {"content": GENERIC_PRIORITIES_CONTENT}


@pytest.mark.asyncio
async def test_priorities_endpoint_returns_real_file_for_owner() -> None:
    response = await _get("/api/priorities", user=OWNER)
    assert response.json()["content"] != GENERIC_PRIORITIES_CONTENT


@pytest.mark.asyncio
async def test_me_endpoint_reports_is_owner_correctly() -> None:
    owner_response = await _get("/api/auth/me", user=OWNER)
    guest_response = await _get("/api/auth/me", user=GUEST)

    assert owner_response.json()["is_owner"] is True
    assert guest_response.json()["is_owner"] is False
