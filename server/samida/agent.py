import json
from dataclasses import dataclass
from pathlib import Path

from samida.providers.base import ModelProvider, ProviderError, ToolCallRequest
from samida.schemas import ChatMessage
from samida.tools import RISK_BY_TOOL, TOOL_SPECS, WorkspaceError, list_directory, log_tool_call, read_file

MAX_TOOL_ITERATIONS = 4


@dataclass
class AgentTurnOutcome:
    resolved_model: str
    message: ChatMessage | None = None
    pending_tool_call: ToolCallRequest | None = None


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


async def run_turn(
    provider: ModelProvider,
    model: str | None,
    messages: list[ChatMessage],
    *,
    workspace: Path | None,
    logs_dir: Path,
) -> AgentTurnOutcome:
    """Run model turns, auto-executing low-risk tool calls, until a final message
    or a medium-risk (confirmation-required) tool call is produced."""
    tools = TOOL_SPECS if workspace is not None else None
    working = list(messages)

    for _ in range(MAX_TOOL_ITERATIONS):
        result = await provider.chat(working, model, tools)
        resolved_model = result.resolved_model
        model = resolved_model

        if result.tool_call is None:
            return AgentTurnOutcome(resolved_model=resolved_model, message=result.message)

        call = result.tool_call
        risk = RISK_BY_TOOL.get(call.name, "medium")
        if risk != "low":
            return AgentTurnOutcome(resolved_model=resolved_model, pending_tool_call=call)

        working.append(_proposal_message(call))
        target = str(call.arguments.get("path", ""))
        try:
            if call.name == "list_directory":
                outcome = list_directory(workspace, call.arguments.get("path", "."))
            elif call.name == "read_file":
                outcome = read_file(workspace, target)
            else:
                outcome = {"error": f"Okänt verktyg: {call.name}"}
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

    raise ProviderError("För många verktygsanrop i rad utan slutgiltigt svar.")


async def resume_after_decision(
    provider: ModelProvider,
    model: str | None,
    messages: list[ChatMessage],
    *,
    call: ToolCallRequest,
    result_payload: dict,
    workspace: Path | None,
    logs_dir: Path,
) -> AgentTurnOutcome:
    working = [*messages, _proposal_message(call), _result_message(call, result_payload)]
    return await run_turn(provider, model, working, workspace=workspace, logs_dir=logs_dir)
