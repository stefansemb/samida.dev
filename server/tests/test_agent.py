from pathlib import Path

import pytest

from samida import agent
from samida.camofox import CamoFoxError
from samida.providers.base import ChatTurnResult, ProviderError, ToolCallRequest
from samida.providers.image_base import ImageGenerationResult
from samida.schemas import ChatMessage
from samida.search import SearchResult
from samida.weather import DailyForecast, WeatherError, WeatherForecast


class _FakeStore:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def save_generated_image(self, image_bytes: bytes, mime_type: str) -> str:
        return "generated-abc.png"

    def save_note(self, owner_id: str, content: str) -> dict:
        self.notes.append(content)
        return {"id": "note-1"}

    def list_notes(self, owner_id: str, query: str | None = None) -> list[dict]:
        matches = [n for n in self.notes if not query or query.lower() in n.lower()]
        return [{"content": n, "created_at": "2026-09-13T00:00:00+00:00"} for n in matches]


class _FakeImageProvider:
    name = "gpt_image"

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        return ImageGenerationResult(image_bytes=b"bytes", mime_type="image/png")


class _QuotaExceededImageProvider:
    name = "nano_banana"

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        raise ProviderError("Gemini rejected the request: quota exceeded")


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
    context = agent.ImageToolContext(providers=[(_FakeImageProvider(), "gpt_image")], store=_FakeStore())

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
async def test_generate_image_tool_falls_back_to_next_provider_on_quota_error() -> None:
    context = agent.ImageToolContext(
        providers=[
            (_QuotaExceededImageProvider(), "nano_banana"),
            (_FakeImageProvider(), "gpt_image"),
        ],
        store=_FakeStore(),
    )

    outcome = await agent.generate_image_tool(context, "en drake")

    assert outcome["image_filename"] == "generated-abc.png"
    assert outcome["provider"] == "gpt_image"


@pytest.mark.asyncio
async def test_generate_image_tool_returns_last_error_when_all_providers_fail() -> None:
    context = agent.ImageToolContext(
        providers=[(_QuotaExceededImageProvider(), "nano_banana")],
        store=_FakeStore(),
    )

    outcome = await agent.generate_image_tool(context, "en drake")

    assert outcome == {"error": "Gemini rejected the request: quota exceeded"}


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


class _FakeCamoFoxClient:
    async def snapshot(self, url: str) -> str:
        return "x" * 10_000


class _FailingCamoFoxClient:
    async def snapshot(self, url: str) -> str:
        raise CamoFoxError("CamoFox kunde inte läsa sidan.")


@pytest.mark.asyncio
async def test_fetch_page_tool_truncates_long_pages() -> None:
    outcome = await agent.fetch_page_tool(_FakeCamoFoxClient(), "https://example.com")
    assert len(outcome["content"]) == agent.MAX_FETCHED_PAGE_CHARS
    assert outcome["truncated"] is True


@pytest.mark.asyncio
async def test_fetch_page_tool_surfaces_camofox_error() -> None:
    outcome = await agent.fetch_page_tool(_FailingCamoFoxClient(), "https://example.com")
    assert outcome == {"error": "CamoFox kunde inte läsa sidan."}


@pytest.mark.asyncio
async def test_fetch_page_tool_without_client_returns_friendly_error() -> None:
    outcome = await agent.fetch_page_tool(None, "https://example.com")
    assert outcome == {"error": "Page fetching is not configured on this server."}


class _FakeWeatherClient:
    async def forecast(self, location: str, days: int = 7) -> WeatherForecast:
        return WeatherForecast(
            location_name="Göteborg, Sweden",
            days=[DailyForecast(date="2026-09-13", condition="clear sky", temperature_min=8.0, temperature_max=18.0, precipitation_probability_max=5)],
        )


class _FailingWeatherClient:
    async def forecast(self, location: str, days: int = 7) -> WeatherForecast:
        raise WeatherError(f"Could not find a location called '{location}'.")


@pytest.mark.asyncio
async def test_weather_tool_returns_forecast() -> None:
    outcome = await agent.weather_tool(_FakeWeatherClient(), "Göteborg")
    assert outcome["location"] == "Göteborg, Sweden"
    assert outcome["forecast"][0]["condition"] == "clear sky"


@pytest.mark.asyncio
async def test_weather_tool_surfaces_weather_error() -> None:
    outcome = await agent.weather_tool(_FailingWeatherClient(), "Nonexistentplacexyz")
    assert outcome == {"error": "Could not find a location called 'Nonexistentplacexyz'."}


@pytest.mark.asyncio
async def test_save_note_tool_saves_and_recall_notes_tool_finds_it() -> None:
    store = _FakeStore()
    context = agent.NotesToolContext(store=store, user_id="user-1")

    saved = await agent.save_note_tool(context, "Köp mjölk")
    assert saved == {"saved": True, "note_id": "note-1"}

    recalled = await agent.recall_notes_tool(context, "")
    assert recalled["notes"] == [{"content": "Köp mjölk", "created_at": "2026-09-13T00:00:00+00:00"}]


@pytest.mark.asyncio
async def test_save_note_tool_rejects_blank_content() -> None:
    context = agent.NotesToolContext(store=_FakeStore(), user_id="user-1")
    outcome = await agent.save_note_tool(context, "   ")
    assert "error" in outcome


@pytest.mark.asyncio
async def test_recall_notes_tool_without_context_returns_friendly_error() -> None:
    outcome = await agent.recall_notes_tool(None, "")
    assert outcome == {"error": "Notes are not available right now."}


@pytest.mark.asyncio
async def test_recall_notes_tool_falls_back_to_all_notes_when_keyword_misses() -> None:
    """A note saved as 'coffee' should still surface for a Swedish query like
    'kaffe' - the DB search is a literal substring match, so it misses
    translations/paraphrases and must fall back rather than say not found."""
    store = _FakeStore()
    context = agent.NotesToolContext(store=store, user_id="user-1")
    await agent.save_note_tool(context, "User likes coffee without milk.")

    outcome = await agent.recall_notes_tool(context, "kaffe")

    assert outcome["notes"] == [{"content": "User likes coffee without milk.", "created_at": "2026-09-13T00:00:00+00:00"}]
