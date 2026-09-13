import json
from dataclasses import dataclass
from pathlib import Path

from samida.camofox import CamoFoxClient, CamoFoxError
from samida.google_integration import GmailError, GoogleCalendarError, GoogleIntegration, GoogleOAuthError
from samida.google_integration import list_recent_emails as fetch_recent_emails
from samida.google_integration import list_upcoming_events as fetch_upcoming_events
from samida.providers.base import ModelProvider, ProviderError, ToolCallRequest
from samida.providers.image_base import ImageProvider
from samida.schemas import ChatMessage
from samida.search import SearchClient, SearchError
from samida.storage import ConversationStore
from samida.tools import (
    GENERAL_TOOL_SPECS,
    RISK_BY_TOOL,
    WORKSPACE_TOOL_SPECS,
    WorkspaceError,
    list_directory,
    log_tool_call,
    read_file,
)
from samida.weather import WeatherClient, WeatherError

MAX_TOOL_ITERATIONS = 4

# In browser-workspace mode, none of these can run on the server (there's no
# server-side directory) - the client executes them and reports back via
# resume_after_decision, same as a human's write_file approval today.
WORKSPACE_TOOL_NAMES = {"list_directory", "read_file", "write_file"}

# Which argument identifies a low-risk tool call for logging/dedup purposes.
_TARGET_ARG_BY_TOOL: dict[str, str] = {
    "generate_image": "prompt",
    "web_search": "query",
    "fetch_page": "url",
    "get_weather": "location",
    "save_note": "content",
    "recall_notes": "query",
    "list_recent_emails": "query",
}


@dataclass
class ImageToolContext:
    """Everything the generate_image tool needs to run and persist its
    result. providers is the user's configured image providers in
    preference order (Pollinations always last, as the free/keyless
    fallback) - empty only if even Pollinations couldn't be built."""

    providers: list[tuple[ImageProvider, str]]
    store: ConversationStore


@dataclass
class NotesToolContext:
    store: ConversationStore
    user_id: str


@dataclass
class GoogleToolContext:
    integration: GoogleIntegration


@dataclass
class AgentTurnOutcome:
    resolved_model: str
    message: ChatMessage | None = None
    pending_tool_call: ToolCallRequest | None = None
    image_filename: str | None = None


def _proposal_message(call: ToolCallRequest) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content="",
        tool_call_id=call.id,
        tool_name=call.name,
        tool_arguments=call.arguments,
    )


def _result_message(call: ToolCallRequest, payload: dict) -> ChatMessage:
    return ChatMessage(
        role="tool",
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=call.id,
    )


async def web_search_tool(client: SearchClient | None, query: str) -> dict:
    if client is None:
        return {"error": "Web search is not configured on this server."}
    if not query.strip():
        return {"error": "Please provide a search query."}
    try:
        results = await client.search(query)
    except SearchError as exc:
        return {"error": str(exc)}
    if not results:
        return {"results": [], "message": "No results found."}
    return {
        "results": [
            {"title": result.title, "url": result.url, "snippet": result.snippet}
            for result in results
        ],
    }


MAX_FETCHED_PAGE_CHARS = 8_000


async def fetch_page_tool(client: CamoFoxClient | None, url: str) -> dict:
    if client is None:
        return {"error": "Page fetching is not configured on this server."}
    if not url.strip():
        return {"error": "Please provide a URL."}
    try:
        content = await client.snapshot(url)
    except CamoFoxError as exc:
        return {"error": str(exc)}
    truncated = content[:MAX_FETCHED_PAGE_CHARS]
    return {"url": url, "content": truncated, "truncated": len(content) > MAX_FETCHED_PAGE_CHARS}


async def weather_tool(client: WeatherClient | None, location: str) -> dict:
    if client is None:
        return {"error": "Weather lookup is not configured on this server."}
    if not location.strip():
        return {"error": "Please provide a city or place name."}
    try:
        result = await client.forecast(location)
    except WeatherError as exc:
        return {"error": str(exc)}
    return {
        "location": result.location_name,
        "forecast": [
            {
                "date": day.date,
                "condition": day.condition,
                "temperature_min": day.temperature_min,
                "temperature_max": day.temperature_max,
                "precipitation_probability_max": day.precipitation_probability_max,
            }
            for day in result.days
        ],
    }


async def save_note_tool(context: NotesToolContext | None, content: str) -> dict:
    if context is None:
        return {"error": "Notes are not available right now."}
    if not content.strip():
        return {"error": "Please provide the note's content."}
    note = context.store.save_note(context.user_id, content)
    return {"saved": True, "note_id": note["id"]}


async def recall_notes_tool(context: NotesToolContext | None, query: str) -> dict:
    if context is None:
        return {"error": "Notes are not available right now."}
    notes = context.store.list_notes(context.user_id, query or None)
    if not notes and query:
        # The keyword is a literal substring match, so it misses paraphrases,
        # translations, or plurals (e.g. a note saved in English won't match
        # a Swedish query). Fall back to the recent list so the model can
        # judge relevance itself instead of reporting a false "not found".
        notes = context.store.list_notes(context.user_id)
    if not notes:
        return {"notes": [], "message": "No notes saved yet."}
    return {"notes": [{"content": note["content"], "created_at": note["created_at"]} for note in notes]}


async def calendar_tool(context: GoogleToolContext | None, max_results: int | None) -> dict:
    if context is None or not context.integration.is_connected():
        return {"error": "Google Calendar is not connected. Connect it under Settings."}
    try:
        access_token = await context.integration.get_valid_access_token()
        events = await fetch_upcoming_events(access_token, max_results or 10)
    except (GoogleOAuthError, GoogleCalendarError) as exc:
        return {"error": str(exc)}
    if not events:
        return {"events": [], "message": "No upcoming events found."}
    return {
        "events": [
            {"summary": e.summary, "start": e.start, "end": e.end, "location": e.location}
            for e in events
        ],
    }


async def email_tool(context: GoogleToolContext | None, query: str) -> dict:
    if context is None or not context.integration.is_connected():
        return {"error": "Gmail is not connected. Connect it under Settings."}
    try:
        access_token = await context.integration.get_valid_access_token()
        emails = await fetch_recent_emails(access_token, query)
    except (GoogleOAuthError, GmailError) as exc:
        return {"error": str(exc)}
    if not emails:
        return {"emails": [], "message": "No matching emails found."}
    return {
        "emails": [
            {"subject": e.subject, "from": e.sender, "date": e.date, "snippet": e.snippet}
            for e in emails
        ],
    }


async def generate_image_tool(context: ImageToolContext | None, prompt: str) -> dict:
    if context is None or not context.providers:
        return {
            "error": "No image generation provider is configured. Add an API key "
            "(GPT Image, Flux, or Gemini) under Settings.",
        }
    if not prompt.strip():
        return {"error": "Please describe the image to generate."}

    last_error: str | None = None
    for image_provider, provider_key in context.providers:
        try:
            result = await image_provider.generate(prompt)
        except ProviderError as exc:
            last_error = str(exc)
            continue
        filename = context.store.save_generated_image(result.image_bytes, result.mime_type)
        payload: dict = {"image_filename": filename, "prompt": prompt, "provider": provider_key}
        if result.revised_prompt:
            payload["revised_prompt"] = result.revised_prompt
        return payload

    return {"error": last_error or "Image generation failed."}


async def run_turn(
    provider: ModelProvider,
    model: str | None,
    messages: list[ChatMessage],
    *,
    workspace: Path | None,
    logs_dir: Path,
    image_context: ImageToolContext | None = None,
    search_client: SearchClient | None = None,
    camofox_client: CamoFoxClient | None = None,
    weather_client: WeatherClient | None = None,
    notes_context: NotesToolContext | None = None,
    google_context: GoogleToolContext | None = None,
    browser_workspace: bool = False,
) -> AgentTurnOutcome:
    """Run model turns, auto-executing low-risk tool calls, until a final message
    or a confirmation-required tool call is produced. A medium-risk tool
    (write_file server-side) needs a human's approval; in browser_workspace
    mode, every workspace tool needs the client to actually execute it (there
    is no server-side directory), so all three pause here regardless of risk."""
    tools = GENERAL_TOOL_SPECS + (WORKSPACE_TOOL_SPECS if (workspace is not None or browser_workspace) else [])
    working = list(messages)
    generated_image_filename: str | None = None

    for _ in range(MAX_TOOL_ITERATIONS):
        result = await provider.chat(working, model, tools)
        resolved_model = result.resolved_model
        model = resolved_model

        if result.tool_call is None:
            return AgentTurnOutcome(
                resolved_model=resolved_model,
                message=result.message,
                image_filename=generated_image_filename,
            )

        call = result.tool_call
        risk = RISK_BY_TOOL.get(call.name, "medium")
        needs_client_execution = browser_workspace and call.name in WORKSPACE_TOOL_NAMES
        if risk != "low" or needs_client_execution:
            return AgentTurnOutcome(
                resolved_model=resolved_model,
                pending_tool_call=call,
                image_filename=generated_image_filename,
            )

        working.append(_proposal_message(call))
        arg_key = _TARGET_ARG_BY_TOOL.get(call.name, "path")
        arg_value = str(call.arguments.get(arg_key, ""))
        target = arg_value[:200]  # only for logging - tool calls below use the full arg_value
        try:
            if call.name == "list_directory":
                outcome = list_directory(workspace, call.arguments.get("path", "."))
            elif call.name == "read_file":
                outcome = read_file(workspace, arg_value)
            elif call.name == "web_search":
                outcome = await web_search_tool(search_client, arg_value)
            elif call.name == "fetch_page":
                outcome = await fetch_page_tool(camofox_client, arg_value)
            elif call.name == "get_weather":
                outcome = await weather_tool(weather_client, arg_value)
            elif call.name == "save_note":
                outcome = await save_note_tool(notes_context, arg_value)
            elif call.name == "recall_notes":
                outcome = await recall_notes_tool(notes_context, arg_value)
            elif call.name == "list_calendar_events":
                outcome = await calendar_tool(google_context, call.arguments.get("max_results"))
            elif call.name == "list_recent_emails":
                outcome = await email_tool(google_context, arg_value)
            elif call.name == "generate_image":
                outcome = await generate_image_tool(image_context, arg_value)
                if "image_filename" in outcome:
                    generated_image_filename = outcome["image_filename"]
            else:
                outcome = {"error": f"Unknown tool: {call.name}"}
            status = "executed"
        except WorkspaceError as exc:
            outcome = {"error": str(exc)}
            status = "failed"
        log_tool_call(
            logs_dir,
            tool_name=call.name,
            target=target,
            risk_level=risk,
            status=status,
            detail=str(outcome),
        )
        working.append(_result_message(call, outcome))

    raise ProviderError("Too many consecutive tool calls without a final response.")


async def resume_after_decision(
    provider: ModelProvider,
    model: str | None,
    messages: list[ChatMessage],
    *,
    call: ToolCallRequest,
    result_payload: dict,
    workspace: Path | None,
    logs_dir: Path,
    image_context: ImageToolContext | None = None,
    search_client: SearchClient | None = None,
    camofox_client: CamoFoxClient | None = None,
    weather_client: WeatherClient | None = None,
    notes_context: NotesToolContext | None = None,
    google_context: GoogleToolContext | None = None,
    browser_workspace: bool = False,
) -> AgentTurnOutcome:
    working = [*messages, _proposal_message(call), _result_message(call, result_payload)]
    return await run_turn(
        provider,
        model,
        working,
        workspace=workspace,
        logs_dir=logs_dir,
        image_context=image_context,
        search_client=search_client,
        camofox_client=camofox_client,
        weather_client=weather_client,
        notes_context=notes_context,
        google_context=google_context,
        browser_workspace=browser_workspace,
    )
