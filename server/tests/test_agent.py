from pathlib import Path

import pytest

from samida import agent
from samida.camofox import CamoFoxError
from samida.google_integration import CalendarEvent, EmailSummary, GmailError, GoogleCalendarError
from samida.providers.base import ChatTurnResult, ProviderError, ToolCallRequest
from samida.providers.image_base import ImageGenerationResult
from samida.schemas import ChatMessage
from samida.search import SearchResult
from samida.simple_fetch import SimpleFetchError
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
async def test_fetch_page_tool_falls_back_to_simple_fetch_on_camofox_error(monkeypatch) -> None:
    async def fake_simple_fetch(url: str) -> str:
        return "plain text content"

    monkeypatch.setattr(agent, "simple_fetch", fake_simple_fetch)
    outcome = await agent.fetch_page_tool(_FailingCamoFoxClient(), "https://example.com")
    assert outcome == {"url": "https://example.com", "content": "plain text content", "truncated": False}


@pytest.mark.asyncio
async def test_fetch_page_tool_without_client_falls_back_to_simple_fetch(monkeypatch) -> None:
    async def fake_simple_fetch(url: str) -> str:
        return "plain text content"

    monkeypatch.setattr(agent, "simple_fetch", fake_simple_fetch)
    outcome = await agent.fetch_page_tool(None, "https://example.com")
    assert outcome == {"url": "https://example.com", "content": "plain text content", "truncated": False}


@pytest.mark.asyncio
async def test_fetch_page_tool_surfaces_simple_fetch_error_when_camofox_also_unavailable(monkeypatch) -> None:
    async def failing_simple_fetch(url: str) -> str:
        raise SimpleFetchError("Could not fetch the page.")

    monkeypatch.setattr(agent, "simple_fetch", failing_simple_fetch)
    outcome = await agent.fetch_page_tool(None, "https://example.com")
    assert outcome == {"error": "Could not fetch the page."}


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


class _FakeGoogleIntegration:
    def __init__(self, connected: bool = True, token: str = "tok") -> None:
        self._connected = connected
        self._token = token

    def is_connected(self) -> bool:
        return self._connected

    async def get_valid_access_token(self) -> str | None:
        return self._token


@pytest.mark.asyncio
async def test_calendar_tool_returns_events(monkeypatch) -> None:
    async def fake_fetch(access_token: str, max_results: int) -> list[CalendarEvent]:
        assert access_token == "tok"
        assert max_results == 5
        return [CalendarEvent(summary="Standup", start="2026-09-13T09:00:00Z", end="2026-09-13T09:15:00Z", location=None)]

    monkeypatch.setattr(agent, "fetch_upcoming_events", fake_fetch)
    context = agent.GoogleToolContext(integration=_FakeGoogleIntegration())

    outcome = await agent.calendar_tool(context, 5)

    assert outcome["events"] == [{"summary": "Standup", "start": "2026-09-13T09:00:00Z", "end": "2026-09-13T09:15:00Z", "location": None}]


@pytest.mark.asyncio
async def test_calendar_tool_when_not_connected() -> None:
    context = agent.GoogleToolContext(integration=_FakeGoogleIntegration(connected=False))
    outcome = await agent.calendar_tool(context, None)
    assert outcome == {"error": "Google Calendar is not connected. Connect it under Settings."}


@pytest.mark.asyncio
async def test_calendar_tool_surfaces_calendar_error(monkeypatch) -> None:
    async def fake_fetch(access_token: str, max_results: int):
        raise GoogleCalendarError("Could not read Google Calendar.")

    monkeypatch.setattr(agent, "fetch_upcoming_events", fake_fetch)
    context = agent.GoogleToolContext(integration=_FakeGoogleIntegration())

    outcome = await agent.calendar_tool(context, None)

    assert outcome == {"error": "Could not read Google Calendar."}


@pytest.mark.asyncio
async def test_email_tool_returns_emails(monkeypatch) -> None:
    async def fake_fetch(access_token: str, query: str) -> list[EmailSummary]:
        assert access_token == "tok"
        assert query == "is:unread"
        return [EmailSummary(subject="Möte imorgon", sender="chef@example.com", date="Sat, 12 Sep 2026", snippet="Hej...")]

    monkeypatch.setattr(agent, "fetch_recent_emails", fake_fetch)
    context = agent.GoogleToolContext(integration=_FakeGoogleIntegration())

    outcome = await agent.email_tool(context, "is:unread")

    assert outcome["emails"] == [{"subject": "Möte imorgon", "from": "chef@example.com", "date": "Sat, 12 Sep 2026", "snippet": "Hej..."}]


@pytest.mark.asyncio
async def test_email_tool_when_not_connected() -> None:
    context = agent.GoogleToolContext(integration=_FakeGoogleIntegration(connected=False))
    outcome = await agent.email_tool(context, "")
    assert outcome == {"error": "Gmail is not connected. Connect it under Settings."}


@pytest.mark.asyncio
async def test_email_tool_surfaces_gmail_error(monkeypatch) -> None:
    async def fake_fetch(access_token: str, query: str):
        raise GmailError("Could not read Gmail.")

    monkeypatch.setattr(agent, "fetch_recent_emails", fake_fetch)
    context = agent.GoogleToolContext(integration=_FakeGoogleIntegration())

    outcome = await agent.email_tool(context, "")

    assert outcome == {"error": "Could not read Gmail."}


@pytest.mark.asyncio
async def test_calendar_tool_and_email_tool_without_context() -> None:
    assert await agent.calendar_tool(None, None) == {"error": "Google Calendar is not connected. Connect it under Settings."}
    assert await agent.email_tool(None, "") == {"error": "Gmail is not connected. Connect it under Settings."}


class _WorkspaceToolProposingProvider:
    """Proposes a given workspace tool once, then a final message."""

    name = "ollama"

    def __init__(self, tool_name: str, arguments: dict) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self.calls = 0
        self.seen_tools: list[dict] | None = None

    async def chat(self, messages, model=None, tools=None) -> ChatTurnResult:
        self.calls += 1
        self.seen_tools = tools
        if self.calls == 1:
            return ChatTurnResult(
                resolved_model="m",
                tool_call=ToolCallRequest(id="call-1", name=self._tool_name, arguments=self._arguments),
            )
        return ChatTurnResult(resolved_model="m", message=ChatMessage(role="assistant", content="done"))


@pytest.mark.asyncio
async def test_browser_workspace_pauses_low_risk_file_tools_for_client_execution(tmp_path: Path) -> None:
    """list_directory and read_file are normally auto-executed server-side
    (low risk) - in browser_workspace mode there is no server-side directory
    at all, so they must pause for the client to execute instead."""
    provider = _WorkspaceToolProposingProvider("read_file", {"path": "notes.txt"})

    outcome = await agent.run_turn(
        provider,
        "m",
        [ChatMessage(role="user", content="read notes.txt")],
        workspace=None,
        logs_dir=tmp_path,
        browser_workspace=True,
    )

    assert outcome.pending_tool_call is not None
    assert outcome.pending_tool_call.name == "read_file"
    assert provider.calls == 1  # never resumed automatically - waits for the client


@pytest.mark.asyncio
async def test_browser_workspace_offers_workspace_tools_without_a_server_workspace(tmp_path: Path) -> None:
    provider = _WorkspaceToolProposingProvider("list_directory", {"path": "."})

    await agent.run_turn(
        provider,
        "m",
        [ChatMessage(role="user", content="what's in the folder?")],
        workspace=None,
        logs_dir=tmp_path,
        browser_workspace=True,
    )

    tool_names = {spec["name"] for spec in (provider.seen_tools or [])}
    assert "read_file" in tool_names
    assert "write_file" in tool_names


@pytest.mark.asyncio
async def test_resume_after_decision_continues_with_browser_workspace_client_result(tmp_path: Path) -> None:
    provider = _WorkspaceToolProposingProvider("write_file", {"path": "a.txt", "content": "hi"})

    outcome = await agent.resume_after_decision(
        provider,
        "m",
        [ChatMessage(role="user", content="read a.txt then write b.txt")],
        call=ToolCallRequest(id="call-0", name="read_file", arguments={"path": "a.txt"}),
        result_payload={"content": "hi there"},
        workspace=None,
        logs_dir=tmp_path,
        browser_workspace=True,
    )

    # The provider proposes another workspace tool (write_file) on this next
    # turn - it must still pause for the client, not try to execute it.
    assert outcome.pending_tool_call is not None
    assert outcome.pending_tool_call.name == "write_file"
