from datetime import UTC, datetime, timedelta

import httpx
import pytest

from samida import google_integration as gi
from samida.config import Settings
from samida.crypto import encrypt_secret
from samida.storage import ConversationStore


def _mock_client(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient  # capture before patching to avoid self-recursion

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(gi.httpx, "AsyncClient", factory)


def test_build_auth_url_includes_offline_access_and_state() -> None:
    url = gi.build_auth_url("client-1", "https://app.samida.dev/api/integrations/google/callback", "state-abc")
    assert "client_id=client-1" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=state-abc" in url
    assert "calendar.readonly" in url
    assert "gmail.readonly" in url


@pytest.mark.asyncio
async def test_exchange_code_returns_token_payload(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/token"
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 3600})

    _mock_client(monkeypatch, handler)

    payload = await gi.exchange_code("id", "secret", "https://x/callback", "the-code")

    assert payload["access_token"] == "a"
    assert payload["refresh_token"] == "r"


@pytest.mark.asyncio
async def test_exchange_code_raises_on_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _mock_client(monkeypatch, handler)

    with pytest.raises(gi.GoogleOAuthError):
        await gi.exchange_code("id", "secret", "https://x/callback", "bad-code")


@pytest.fixture
def store(tmp_path) -> ConversationStore:
    return ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")


@pytest.fixture
def settings() -> Settings:
    from cryptography.fernet import Fernet

    return Settings(secret_key=Fernet.generate_key().decode())


@pytest.fixture
def owner_id(store: ConversationStore) -> str:
    return store.create_user("owner@example.com", "hash")["id"]


@pytest.mark.asyncio
async def test_get_valid_access_token_returns_stored_token_when_not_expired(store, settings, owner_id) -> None:
    store.save_oauth_connection(
        owner_id,
        gi.PROVIDER,
        encrypt_secret("still-valid-token", settings),
        encrypt_secret("refresh-token", settings),
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "calendar.readonly gmail.readonly",
    )
    integration = gi.GoogleIntegration(store, settings, owner_id)

    assert integration.is_connected() is True
    assert await integration.get_valid_access_token() == "still-valid-token"


@pytest.mark.asyncio
async def test_get_valid_access_token_refreshes_when_expired(monkeypatch, store, settings, owner_id) -> None:
    store.save_oauth_connection(
        owner_id,
        gi.PROVIDER,
        encrypt_secret("expired-token", settings),
        encrypt_secret("refresh-token", settings),
        (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        "calendar.readonly gmail.readonly",
    )
    settings.google_client_id = "id"
    settings.google_client_secret = "secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(httpx.QueryParams(request.content.decode()))["grant_type"] == "refresh_token"
        return httpx.Response(200, json={"access_token": "fresh-token", "expires_in": 3600})

    _mock_client(monkeypatch, handler)
    integration = gi.GoogleIntegration(store, settings, owner_id)

    token = await integration.get_valid_access_token()

    assert token == "fresh-token"
    connection = store.get_oauth_connection(owner_id, gi.PROVIDER)
    from samida.crypto import decrypt_secret

    assert decrypt_secret(connection["access_token_encrypted"], settings) == "fresh-token"


@pytest.mark.asyncio
async def test_get_valid_access_token_returns_none_when_not_connected(store, settings, owner_id) -> None:
    integration = gi.GoogleIntegration(store, settings, owner_id)
    assert await integration.get_valid_access_token() is None


def test_disconnect_removes_the_connection(store, settings, owner_id) -> None:
    store.save_oauth_connection(
        owner_id, gi.PROVIDER, encrypt_secret("a", settings), encrypt_secret("r", settings),
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "scope",
    )
    integration = gi.GoogleIntegration(store, settings, owner_id)

    integration.disconnect()

    assert integration.is_connected() is False


@pytest.mark.asyncio
async def test_list_upcoming_events_parses_items(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json={"items": [{"summary": "Standup", "start": {"dateTime": "2026-09-13T09:00:00Z"}, "end": {"dateTime": "2026-09-13T09:15:00Z"}, "location": "Zoom"}]},
        )

    _mock_client(monkeypatch, handler)

    events = await gi.list_upcoming_events("tok")

    assert events[0].summary == "Standup"
    assert events[0].location == "Zoom"


@pytest.mark.asyncio
async def test_list_upcoming_events_raises_calendar_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid token"})

    _mock_client(monkeypatch, handler)

    with pytest.raises(gi.GoogleCalendarError):
        await gi.list_upcoming_events("bad-tok")


@pytest.mark.asyncio
async def test_list_recent_emails_fetches_list_then_details(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gmail/v1/users/me/messages":
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        assert request.url.path == "/gmail/v1/users/me/messages/m1"
        return httpx.Response(
            200,
            json={
                "snippet": "Hej, kan vi...",
                "payload": {"headers": [{"name": "Subject", "value": "Möte imorgon"}, {"name": "From", "value": "chef@example.com"}, {"name": "Date", "value": "Sat, 12 Sep 2026 10:00:00 +0000"}]},
            },
        )

    _mock_client(monkeypatch, handler)

    emails = await gi.list_recent_emails("tok")

    assert emails[0].subject == "Möte imorgon"
    assert emails[0].sender == "chef@example.com"
    assert emails[0].snippet == "Hej, kan vi..."


@pytest.mark.asyncio
async def test_list_recent_emails_raises_gmail_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "insufficient scope"})

    _mock_client(monkeypatch, handler)

    with pytest.raises(gi.GmailError):
        await gi.list_recent_emails("bad-tok")
