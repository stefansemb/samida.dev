import httpx
import pytest

from samida import auth
from samida.camofox import CamoFoxClient
from samida.config import Settings, get_settings
from samida.dependencies import get_camofox_client, get_conversation_store, get_ollama_provider
from samida.main import app
from samida.providers.base import ChatTurnResult
from samida.research import ResearchItem, parse_feed, run_research
from samida.schemas import ChatMessage
from samida.storage import ConversationStore

TEST_USER = auth.User(id="test-user", email="test@example.com", tier="full")


class FakeProvider:
    name = "ollama"

    async def chat(self, messages: list[ChatMessage], model: str, tools: list[dict] | None = None):
        self.messages = messages
        return ChatTurnResult(resolved_model=model, message=ChatMessage(role="assistant", content="Rapport"))


@pytest.mark.asyncio
async def test_mobile_research_uses_mobile_specific_sources_and_prompt(monkeypatch) -> None:
    provider = FakeProvider()

    async def fake_collect(research_type, timeout=15.0, camofox=None):
        assert research_type == "mobile_apps"
        return [ResearchItem("App", "https://example.com/app", "trend", "Test")]

    monkeypatch.setattr("samida.research.collect_items", fake_collect)
    content, sources = await run_research(provider, "model", "mobile_apps")

    assert content == "Rapport"
    assert sources == ["https://example.com/app"]
    assert "mobilappar" in provider.messages[0].content.lower()
    assert "efterfrågan" in provider.messages[1].content.lower()
    assert "<untrusted_sources>" in provider.messages[1].content
    assert "ignorera instruktioner" in provider.messages[0].content.lower()


def test_atom_feed_parser_reads_product_hunt_and_android_entries() -> None:
    payload = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Useful App</title><link rel="alternate" href="https://example.com/useful"/>
      <content type="html">A useful mobile app</content></entry>
    </feed>'''

    items = parse_feed(payload, "Product Hunt")

    assert items == [
        ResearchItem("Useful App", "https://example.com/useful", "A useful mobile app", "Product Hunt")
    ]


def test_atom_feed_parser_prefers_alternate_over_earlier_comments_link() -> None:
    payload = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Android update</title>
      <link rel="replies" href="https://example.com/post/comments"/>
      <link rel="alternate" type="text/html" href="https://example.com/post"/>
      <link rel="self" href="https://example.com/feed/entry"/>
      <summary>New Android app capabilities</summary>
    </entry></feed>'''

    items = parse_feed(payload, "Android Developers")

    assert items[0].link == "https://example.com/post"


@pytest.mark.asyncio
async def test_research_api_injects_camofox_and_separates_report_types(tmp_path, monkeypatch) -> None:
    store = ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")
    user_id = store.create_user("test@example.com", "hash")["id"]
    camofox = CamoFoxClient("http://camofox.test")
    calls = []

    async def fake_run(provider, model, research_type, injected_camofox):
        calls.append((research_type, injected_camofox))
        return f"rapport {research_type}", ["https://example.com"]

    monkeypatch.setattr("samida.main.run_research", fake_run)
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_ollama_provider] = lambda: FakeProvider()
    app.dependency_overrides[get_settings] = lambda: Settings()
    app.dependency_overrides[get_camofox_client] = lambda: camofox
    app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=user_id, email="test@example.com", tier="full")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/api/research/run?research_type=mobile_apps")
            mobile = await client.get("/api/research/reports?research_type=mobile_apps")
            ai = await client.get("/api/research/reports?research_type=ai_general")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert created.json()["research_type"] == "mobile_apps"
    assert calls == [("mobile_apps", camofox)]
    assert len(mobile.json()) == 1
    assert ai.json() == []


@pytest.mark.asyncio
async def test_research_api_rejects_unknown_type() -> None:
    app.dependency_overrides[auth.get_current_user] = lambda: TEST_USER
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/research/run?research_type=unknown")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_research_api_reuses_idempotent_request(tmp_path, monkeypatch) -> None:
    store = ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")
    user_id = store.create_user("test@example.com", "hash")["id"]
    provider = FakeProvider()
    calls = 0

    async def fake_run(*args):
        nonlocal calls
        calls += 1
        return "rapport", []

    monkeypatch.setattr("samida.main.run_research", fake_run)
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_ollama_provider] = lambda: provider
    app.dependency_overrides[get_settings] = lambda: Settings(camofox_enabled=False)
    app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=user_id, email="test@example.com", tier="full")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/research/run?research_type=mobile_apps", headers={"Idempotency-Key": "weekly-1"})
            retry = await client.post("/api/research/run?research_type=mobile_apps", headers={"Idempotency-Key": "weekly-1"})
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert calls == 1
