from pathlib import Path

import httpx
import pytest

from samida import auth
from samida.config import Settings, get_settings
from samida.dependencies import get_conversation_store
from samida.main import app, get_chat_provider_factory
from samida.providers.base import ChatTurnResult, ToolCallRequest
from samida.schemas import ChatMessage
from samida.storage import ConversationStore


class _FakeProvider:
    name = "ollama"

    def __init__(self, first_call: ToolCallRequest, final_message: str = "Done!") -> None:
        self._first_call = first_call
        self._final_message = final_message
        self.calls = 0
        self.seen_tools: list[dict] | None = None

    async def chat(self, messages: list[ChatMessage], model: str | None = None, tools: list[dict] | None = None) -> ChatTurnResult:
        self.calls += 1
        self.seen_tools = tools
        if self.calls == 1:
            return ChatTurnResult(resolved_model="test-model", tool_call=self._first_call)
        return ChatTurnResult(resolved_model="test-model", message=ChatMessage(role="assistant", content=self._final_message))


class _FakeChatProviderFactory:
    def __init__(self, provider: _FakeProvider) -> None:
        self._provider = provider

    async def build(self, provider_key: str, requested_model: str | None):
        return self._provider, requested_model or "test-model"


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")


@pytest.fixture
def owner_id(store: ConversationStore) -> str:
    return store.create_user("owner@example.com", "hash")["id"]


@pytest.mark.asyncio
async def test_browser_workspace_chat_pauses_for_client_execution(store: ConversationStore, owner_id: str) -> None:
    conversation = store.create_conversation(owner_id)
    provider = _FakeProvider(ToolCallRequest(id="call-1", name="read_file", arguments={"path": "notes.txt"}))

    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_chat_provider_factory] = lambda: _FakeChatProviderFactory(provider)
    app.dependency_overrides[get_settings] = lambda: Settings()
    app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=owner_id, email="owner@example.com", tier="full")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/conversations/{conversation['id']}/chat",
                json={"content": "read notes.txt", "provider": "ollama", "browser_workspace": True},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["pending_tool_call"]["tool_name"] == "read_file"
    assert body["pending_tool_call"]["browser_workspace"] is True
    tool_names = {spec["name"] for spec in (provider.seen_tools or [])}
    assert "read_file" in tool_names


@pytest.mark.asyncio
async def test_client_result_endpoint_resumes_the_turn(store: ConversationStore, owner_id: str) -> None:
    conversation = store.create_conversation(owner_id)
    provider = _FakeProvider(ToolCallRequest(id="call-1", name="read_file", arguments={"path": "notes.txt"}))

    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_chat_provider_factory] = lambda: _FakeChatProviderFactory(provider)
    app.dependency_overrides[get_settings] = lambda: Settings()
    app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=owner_id, email="owner@example.com", tier="full")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                f"/api/conversations/{conversation['id']}/chat",
                json={"content": "read notes.txt", "provider": "ollama", "browser_workspace": True},
            )
            tool_call_id = first.json()["pending_tool_call"]["id"]

            resumed = await client.post(
                f"/api/conversations/{conversation['id']}/tool-calls/{tool_call_id}/client-result",
                json={"result": {"content": "hello from disk"}},
            )
    finally:
        app.dependency_overrides.clear()

    assert resumed.status_code == 200
    assert resumed.json()["assistant_message"]["content"] == "Done!"
    assert resumed.json()["pending_tool_call"] is None


@pytest.mark.asyncio
async def test_client_result_rejected_when_call_is_not_browser_workspace(store: ConversationStore, owner_id: str) -> None:
    """A server-side write_file (human-approval flow) must not be resolved
    through the client-result endpoint - that would let it skip the
    approve/reject decision entirely."""
    conversation = store.create_conversation(owner_id)
    record = store.create_pending_tool_call(
        conversation["id"], owner_id, "call-1", "write_file", {"path": "a.txt", "content": "hi"},
        "medium", "ollama", "test-model", "minimal", "",
    )
    assert record["browser_workspace"] is False

    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings()
    app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=owner_id, email="owner@example.com", tier="full")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/conversations/{conversation['id']}/tool-calls/call-1/client-result",
                json={"result": {"content": "sneaky"}},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
