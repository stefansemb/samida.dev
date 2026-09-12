import json
from dataclasses import dataclass
from pathlib import Path

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

MAX_TOOL_ITERATIONS = 4


@dataclass
class ImageToolContext:
    """Everything the generate_image tool needs to run and persist its
    result. image_provider is None when the calling user hasn't configured
    any image-generation key yet."""

    image_provider: ImageProvider | None
    provider_key: str | None
    store: ConversationStore


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


async def generate_image_tool(context: ImageToolContext | None, prompt: str) -> dict:
    if context is None or context.image_provider is None:
        return {
            "error": "No image generation provider is configured. Add an API key "
            "(GPT Image, Flux, or Gemini) under Settings.",
        }
    if not prompt.strip():
        return {"error": "Please describe the image to generate."}
    try:
        result = await context.image_provider.generate(prompt)
    except ProviderError as exc:
        return {"error": str(exc)}
    filename = context.store.save_generated_image(result.image_bytes, result.mime_type)
    payload: dict = {"image_filename": filename, "prompt": prompt, "provider": context.provider_key}
    if result.revised_prompt:
        payload["revised_prompt"] = result.revised_prompt
    return payload


async def run_turn(
    provider: ModelProvider,
    model: str | None,
    messages: list[ChatMessage],
    *,
    workspace: Path | None,
    logs_dir: Path,
    image_context: ImageToolContext | None = None,
    search_client: SearchClient | None = None,
) -> AgentTurnOutcome:
    """Run model turns, auto-executing low-risk tool calls, until a final message
    or a medium-risk (confirmation-required) tool call is produced."""
    tools = GENERAL_TOOL_SPECS + (WORKSPACE_TOOL_SPECS if workspace is not None else [])
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
        if risk != "low":
            return AgentTurnOutcome(
                resolved_model=resolved_model,
                pending_tool_call=call,
                image_filename=generated_image_filename,
            )

        working.append(_proposal_message(call))
        target = (
            str(call.arguments.get("prompt", ""))[:200]
            if call.name == "generate_image"
            else str(call.arguments.get("query", ""))[:200]
            if call.name == "web_search"
            else str(call.arguments.get("path", ""))
        )
        try:
            if call.name == "list_directory":
                outcome = list_directory(workspace, call.arguments.get("path", "."))
            elif call.name == "read_file":
                outcome = read_file(workspace, target)
            elif call.name == "web_search":
                outcome = await web_search_tool(search_client, target)
            elif call.name == "generate_image":
                outcome = await generate_image_tool(image_context, str(call.arguments.get("prompt", "")))
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
    )
