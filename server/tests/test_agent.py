from pathlib import Path

import pytest

from samida import agent
from samida.providers.base import ChatTurnResult, ToolCallRequest
from samida.providers.image_base import ImageGenerationResult
from samida.schemas import ChatMessage
from samida.search import SearchResult


class _FakeStore:
    def save_generated_image(self, image_bytes: bytes, mime_type: str) -> str:
        return "generated-abc.png"


class _FakeImageProvider:
    name = "gpt_image"

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        return ImageGenerationResult(image_bytes=b"bytes", mime_type="image/png")


class _ToolThenFinalProvider:
    """A fake ModelProvider that first proposes a generate_image tool call,
    then returns a final text message on the next turn."""

    name = "ollama"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[ChatMessage], model: str | None = None, tools: list[dict] | None = None) -> ChatTurnResult:
        self.calls += 1
        if self.calls == 1:
            return ChatTurnResult(
                resolved_model="test-model",
                tool_call=ToolCallRequest(id="call-1", name="generate_image", arguments={"prompt": "en drake"}),
            )
        return ChatTurnResult(resolved_model="test-model", message=ChatMessage(role="assistant", content="Här är bilden!"))


@pytest.mark.asyncio
async def test_run_turn_executes_generate_image_and_attaches_filename(tmp_path: Path) -> None:
    provider = _ToolThenFinalProvider()
    context = agent.ImageToolContext(image_provider=_FakeImageProvider(), provider_key="gpt_image", store=_FakeStore())

    outcome = await agent.run_turn(
        provider,
        "test-model",
        [ChatMessage(role="user", content="Rita en drake")],
        workspace=None,
        logs_dir=tmp_path,
        image_context=context,
    )

    assert outcome.image_filename == "generated-abc.png"
    assert outcome.message is not None
    assert outcome.message.content == "Här är bilden!"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_run_turn_offers_generate_image_tool_without_a_workspace(tmp_path: Path) -> None:
    """generate_image must work even with no workspace set (unlike the
    file tools, which require one)."""

    class _RecordingProvider:
        name = "ollama"

        def __init__(self) -> None:
            self.seen_tools: list[dict] | None = None

        async def chat(self, messages, model=None, tools=None) -> ChatTurnResult:
            self.seen_tools = tools
            return ChatTurnResult(resolved_model="m", message=ChatMessage(role="assistant", content="ok"))

    provider = _RecordingProvider()
    await agent.run_turn(
        provider,
        "m",
        [ChatMessage(role="user", content="hej")],
        workspace=None,
        logs_dir=tmp_path,
        image_context=None,
    )

    tool_names = {spec["name"] for spec in (provider.seen_tools or [])}
    assert "generate_image" in tool_names
    assert "write_file" not in tool_names


@pytest.mark.asyncio
async def test_run_turn_without_image_context_returns_friendly_error_in_tool_result(tmp_path: Path) -> None:
    provider = _ToolThenFinalProvider()

    outcome = await agent.run_turn(
        provider,
        "test-model",
        [ChatMessage(role="user", content="Rita en drake")],
        workspace=None,
        logs_dir=tmp_path,
        image_context=None,
    )

    assert outcome.image_filename is None
    assert outcome.message is not None


class _FakeSearchClient:
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        return [SearchResult(title="SAMIDA", url="https://samida.dev", snippet="En personlig assistent.")]


class _WebSearchThenFinalProvider:
    """Works no matter which provider answers - the point of implementing
    web_search as our own tool rather than a provider-hosted one."""

    name = "anthropic"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[ChatMessage], model: str | None = None, tools: list[dict] | None = None) -> ChatTurnResult:
        self.calls += 1
        if self.calls == 1:
            return ChatTurnResult(
                resolved_model="test-model",
                tool_call=ToolCallRequest(id="call-1", name="web_search", arguments={"query": "vad är samida"}),
            )
        return ChatTurnResult(resolved_model="test-model", message=ChatMessage(role="assistant", content="SAMIDA är en assistent."))


@pytest.mark.asyncio
async def test_run_turn_executes_web_search_regardless_of_provider(tmp_path: Path) -> None:
    provider = _WebSearchThenFinalProvider()

    outcome = await agent.run_turn(
        provider,
        "test-model",
        [ChatMessage(role="user", content="Vad är SAMIDA?")],
        workspace=None,
        logs_dir=tmp_path,
        search_client=_FakeSearchClient(),
    )

    assert outcome.message is not None
    assert outcome.message.content == "SAMIDA är en assistent."
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_web_search_tool_without_client_returns_friendly_error() -> None:
    outcome = await agent.web_search_tool(None, "vad är samida")
    assert outcome == {"error": "Web search is not configured on this server."}
