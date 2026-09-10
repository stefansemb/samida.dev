import asyncio
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from samida import agent, tools as tool_impl
from samida.config import Settings, get_settings
from samida.context import ContextBuilder, ContextError
from samida.dependencies import (
    get_anthropic_provider,
    get_context_builder,
    get_conversation_store,
    get_ocr_service,
    get_openai_provider,
    get_ollama_provider,
)
from samida.providers import AnthropicProvider, ModelProvider, OllamaProvider, OpenAIProvider, ProviderError, ToolCallRequest
from samida.ocr import OcrService
from samida.research import run_research
from samida.camofox import CamoFoxClient
from samida.dependencies import get_camofox_client
from samida.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ContextPreviewRequest,
    ContextPreviewResponse,
    ConversationChatRequest,
    ConversationChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    ConversationSummary,
    HealthResponse,
    PendingToolCall,
    StoredMessage,
    ResearchReport,
    Reminder, ReminderCreate,
    ToolCallDecisionResponse,
    WorkspacePickResponse,
)
from samida.storage import ConversationStore, NotFoundError, StorageError

app = FastAPI(
    title="SAMIDA API",
    version="0.1.0",
    description="Local backend for the SAMIDA assistant.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://[::1]:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

@app.post("/api/workspace/pick", response_model=WorkspacePickResponse)
def pick_workspace() -> WorkspacePickResponse:
    """Open a local native folder picker for the desktop SAMIDA instance."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(title="Välj arbetskatalog") or None
    finally:
        root.destroy()
    return WorkspacePickResponse(path=path)


def pick_provider(
    name: str,
    ollama: OllamaProvider,
    openai: OpenAIProvider,
    anthropic: AnthropicProvider,
) -> ModelProvider:
    if name == "openai":
        return openai
    if name == "anthropic":
        return anthropic
    return ollama


def runtime_message(provider: ModelProvider, model: str) -> ChatMessage:
    return ChatMessage(
        role="system",
        content=(
            "Intern runtime-information: detta svar genereras av "
            f"provider '{provider.name}' med modell '{model}'. "
            "Om användaren frågar vilken modell som används, ange dessa "
            "värden exakt och gissa inte."
        ),
    )


@app.get("/api/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
    ollama: OllamaProvider = Depends(get_ollama_provider),
) -> HealthResponse:
    try:
        models = await ollama.model_names()
    except ProviderError:
        return HealthResponse(
            status="degraded",
            ollama_reachable=False,
            configured_model=settings.ollama_chat_model,
            model_available=False,
            configured_vision_model=settings.ollama_vision_model,
            vision_model_available=False,
            available_models=[],
            openai_configured=settings.openai_api_key is not None,
            anthropic_configured=settings.anthropic_api_key is not None,
        )

    available = settings.ollama_chat_model in models
    vision_available = settings.ollama_vision_model in models
    return HealthResponse(
        status="ok" if available and vision_available else "degraded",
        ollama_reachable=True,
        configured_model=settings.ollama_chat_model,
        model_available=available,
        configured_vision_model=settings.ollama_vision_model,
        vision_model_available=vision_available,
        available_models=models,
        openai_configured=settings.openai_api_key is not None,
        anthropic_configured=settings.anthropic_api_key is not None,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
    ollama: OllamaProvider = Depends(get_ollama_provider),
    openai: OpenAIProvider = Depends(get_openai_provider),
    anthropic: AnthropicProvider = Depends(get_anthropic_provider),
    context_builder: ContextBuilder = Depends(get_context_builder),
) -> ChatResponse:
    try:
        context = context_builder.build(request.messages, request.profile, request.working_directory)
        provider: ModelProvider = pick_provider(request.provider, ollama, openai, anthropic)
        selected_model = request.model
        if selected_model is None and any(message.images for message in request.messages):
            selected_model = settings.ollama_vision_model
        resolved_model = selected_model or settings.ollama_chat_model
        turn = await provider.chat(
            [context.system_message, runtime_message(provider, resolved_model), *request.messages],
            selected_model,
        )
        if turn.message is None:
            raise ProviderError("Modellen försökte anropa ett verktyg, vilket inte stöds här.")
    except ContextError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        provider=provider.name,
        model=turn.resolved_model,
        message=turn.message,
        context_files=context.included_files,
        usage=getattr(provider, "last_usage", None),
    )


@app.post("/api/context/preview", response_model=ContextPreviewResponse)
async def preview_context(
    request: ContextPreviewRequest,
    context_builder: ContextBuilder = Depends(get_context_builder),
) -> ContextPreviewResponse:
    try:
        context = context_builder.build(request.messages)
    except ContextError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ContextPreviewResponse(
        context_files=context.included_files,
        system_prompt=context.system_message.content,
    )


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations(
    store: ConversationStore = Depends(get_conversation_store),
) -> list[dict]:
    return store.list_conversations()


@app.get("/api/research/reports", response_model=list[ResearchReport])
def list_research_reports(
    research_type: Literal["ai_general", "mobile_apps"] = "ai_general",
    store: ConversationStore = Depends(get_conversation_store),
) -> list[dict]:
    return store.list_research_reports(research_type)

@app.get("/api/reminders", response_model=list[Reminder])
def list_reminders(store: ConversationStore = Depends(get_conversation_store)) -> list[dict]:
    return store.list_reminders()

@app.get("/api/priorities")
def get_priorities(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    path = settings.project_root / "memory" / "priorities.md"
    return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}

@app.post("/api/reminders", response_model=Reminder, status_code=201)
def create_reminder(request: ReminderCreate, store: ConversationStore = Depends(get_conversation_store)) -> dict:
    return store.create_reminder(request.text, request.due_at, request.recurrence, request.range_start, request.range_end, request.event_at)

@app.post("/api/reminders/{reminder_id}/complete", status_code=204)
def complete_reminder(reminder_id: str, store: ConversationStore = Depends(get_conversation_store)) -> None:
    store.complete_reminder(reminder_id)

@app.delete("/api/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: str, store: ConversationStore = Depends(get_conversation_store)) -> None:
    store.delete_reminder(reminder_id)


@app.post("/api/research/run", response_model=ResearchReport, status_code=201)
async def create_research_report(
    research_type: Literal["ai_general", "mobile_apps"] = "ai_general",
    ollama: OllamaProvider = Depends(get_ollama_provider),
    settings: Settings = Depends(get_settings),
    store: ConversationStore = Depends(get_conversation_store),
    camofox: CamoFoxClient | None = Depends(get_camofox_client),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
) -> dict:
    if idempotency_key:
        existing = store.get_research_report_by_idempotency_key(idempotency_key)
        if existing:
            return existing
    try:
        content, sources = await run_research(ollama, settings.ollama_chat_model, research_type, camofox)
        return store.create_research_report(content, sources, research_type, idempotency_key)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(
    request: ConversationCreate,
    store: ConversationStore = Depends(get_conversation_store),
) -> dict:
    return store.create_conversation(request.title)


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    store: ConversationStore = Depends(get_conversation_store),
) -> dict:
    try:
        conversation = store.get_conversation(conversation_id)
        return {**conversation, "messages": store.messages(conversation_id)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    request: ConversationRename,
    store: ConversationStore = Depends(get_conversation_store),
) -> dict:
    try:
        return store.rename_conversation(conversation_id, request.title)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    try:
        store.delete_conversation(conversation_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/api/conversations/{conversation_id}/chat",
    response_model=ConversationChatResponse,
)
async def conversation_chat(
    conversation_id: str,
    request: ConversationChatRequest,
    ollama: OllamaProvider = Depends(get_ollama_provider),
    openai: OpenAIProvider = Depends(get_openai_provider),
    anthropic: AnthropicProvider = Depends(get_anthropic_provider),
    context_builder: ContextBuilder = Depends(get_context_builder),
    store: ConversationStore = Depends(get_conversation_store),
    ocr: OcrService = Depends(get_ocr_service),
    settings: Settings = Depends(get_settings),
) -> ConversationChatResponse:
    image_filename = None
    image_base64 = None
    ocr_text = None
    try:
        store.get_conversation(conversation_id)
        if request.image:
            image_filename, image_base64 = store.save_image(request.image)
            ocr_text = await asyncio.to_thread(
                ocr.extract_text,
                store.attachment_path(image_filename),
            )
        history = [
            StoredMessage.model_validate(message)
            for message in store.messages(conversation_id)
        ]
        context_messages = [
            ChatMessage(
                role=message.role,
                content=message.content or "[Skärmdump]",
            )
            for message in history
        ]
        current_content = request.content.strip() or "Beskriv och analysera bilden."
        if ocr_text:
            current_content += (
                "\n\nLokalt OCR-verktyg läste följande text ur bilden. "
                "Använd den som stöd och kontrollera den mot bilden:\n---\n"
                f"{ocr_text}\n---"
            )
        current = ChatMessage(
            role="user",
            content=current_content,
            images=[image_base64] if image_base64 else [],
        )
        context = context_builder.build([*context_messages, current], request.profile, request.working_directory)
        model_history = [
            ChatMessage.model_validate(message)
            for message in store.model_messages(conversation_id)
        ]
        provider: ModelProvider = pick_provider(request.provider, ollama, openai, anthropic)
        selected_model = request.model
        if image_base64 and request.provider == "ollama":
            selected_model = settings.ollama_vision_model
        resolved_model = selected_model or settings.ollama_chat_model
        workspace = _resolve_workspace(request.working_directory)
        turn = await agent.run_turn(
            provider,
            selected_model,
            [
                context.system_message,
                runtime_message(provider, resolved_model),
                *model_history,
                current,
            ],
            workspace=workspace,
            logs_dir=settings.resolved_logs_dir(),
        )

        pending_tool_call: PendingToolCall | None = None
        if turn.pending_tool_call is not None:
            call = turn.pending_tool_call
            risk = tool_impl.RISK_BY_TOOL.get(call.name, "medium")
            record = store.create_pending_tool_call(
                conversation_id,
                call.id,
                call.name,
                call.arguments,
                risk,
                provider.name,
                turn.resolved_model,
                request.profile,
                request.working_directory or "",
            )
            conversation, user_message, assistant_message = store.add_exchange(
                conversation_id,
                request.content.strip(),
                _tool_proposal_text(call),
                image_filename,
                ocr_text,
                assistant_tool_call_id=call.id,
            )
            pending_tool_call = PendingToolCall(
                id=record["id"],
                tool_name=record["tool_name"],
                arguments=record["arguments"],
                risk_level=record["risk_level"],
                status=record["status"],
                created_at=record["created_at"],
            )
        else:
            conversation, user_message, assistant_message = store.add_exchange(
                conversation_id,
                request.content.strip(),
                turn.message.content,
                image_filename,
                ocr_text,
            )
    except NotFoundError as exc:
        if image_filename:
            store.attachment_path(image_filename).unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (StorageError, ContextError) as exc:
        if image_filename:
            store.attachment_path(image_filename).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        if image_filename:
            store.attachment_path(image_filename).unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ConversationChatResponse(
        conversation=conversation,
        user_message=user_message,
        assistant_message=assistant_message,
        provider=provider.name,
        model=turn.resolved_model,
        context_files=context.included_files,
        ocr_text=ocr_text,
        usage=getattr(provider, "last_usage", None),
        pending_tool_call=pending_tool_call,
    )


def _resolve_workspace(working_directory: str | None) -> Path | None:
    if not working_directory or not working_directory.strip():
        return None
    candidate = Path(working_directory.strip())
    return candidate if candidate.is_dir() else None


def _tool_proposal_text(call: ToolCallRequest) -> str:
    if call.name == "write_file":
        path = call.arguments.get("path", "?")
        content = call.arguments.get("content", "")
        lines = content.count("\n") + 1 if content else 0
        return f'Föreslår att skriva till "{path}" ({lines} rader). Väntar på ditt godkännande.'
    return f"Föreslår att köra verktyget {call.name}. Väntar på ditt godkännande."


@app.post(
    "/api/conversations/{conversation_id}/tool-calls/{tool_call_id}/approve",
    response_model=ToolCallDecisionResponse,
)
async def approve_tool_call(
    conversation_id: str,
    tool_call_id: str,
    ollama: OllamaProvider = Depends(get_ollama_provider),
    openai: OpenAIProvider = Depends(get_openai_provider),
    anthropic: AnthropicProvider = Depends(get_anthropic_provider),
    context_builder: ContextBuilder = Depends(get_context_builder),
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
) -> ToolCallDecisionResponse:
    return await _resolve_tool_call(
        conversation_id,
        tool_call_id,
        approve=True,
        ollama=ollama,
        openai=openai,
        anthropic=anthropic,
        context_builder=context_builder,
        store=store,
        settings=settings,
    )


@app.post(
    "/api/conversations/{conversation_id}/tool-calls/{tool_call_id}/reject",
    response_model=ToolCallDecisionResponse,
)
async def reject_tool_call(
    conversation_id: str,
    tool_call_id: str,
    ollama: OllamaProvider = Depends(get_ollama_provider),
    openai: OpenAIProvider = Depends(get_openai_provider),
    anthropic: AnthropicProvider = Depends(get_anthropic_provider),
    context_builder: ContextBuilder = Depends(get_context_builder),
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
) -> ToolCallDecisionResponse:
    return await _resolve_tool_call(
        conversation_id,
        tool_call_id,
        approve=False,
        ollama=ollama,
        openai=openai,
        anthropic=anthropic,
        context_builder=context_builder,
        store=store,
        settings=settings,
    )


async def _resolve_tool_call(
    conversation_id: str,
    tool_call_id: str,
    *,
    approve: bool,
    ollama: OllamaProvider,
    openai: OpenAIProvider,
    anthropic: AnthropicProvider,
    context_builder: ContextBuilder,
    store: ConversationStore,
    settings: Settings,
) -> ToolCallDecisionResponse:
    try:
        record = store.get_tool_call(tool_call_id)
        if record["conversation_id"] != conversation_id:
            raise NotFoundError("Verktygsanropet hör inte till denna chatt.")
        if record["status"] != "pending":
            raise StorageError("Verktygsanropet är redan hanterat.")

        call = ToolCallRequest(id=record["id"], name=record["tool_name"], arguments=record["arguments"])
        workspace = _resolve_workspace(record["working_directory"])
        target = str(call.arguments.get("path", ""))

        if approve:
            try:
                outcome = tool_impl.write_file(workspace, target, call.arguments.get("content", ""))
                status = "executed"
            except tool_impl.WorkspaceError as exc:
                outcome = {"error": str(exc)}
                status = "failed"
        else:
            outcome = {"status": "rejected", "message": "Användaren avvisade åtgärden."}
            status = "rejected"
        tool_impl.log_tool_call(
            settings.resolved_logs_dir(),
            tool_name=call.name,
            target=target,
            risk_level=record["risk_level"],
            status=status,
            detail=str(outcome),
        )
        store.resolve_tool_call(tool_call_id, status=status, result=outcome)

        history = [StoredMessage.model_validate(item) for item in store.messages(conversation_id)]
        context_messages = [ChatMessage(role=item.role, content=item.content or "[Skärmdump]") for item in history]
        context = context_builder.build(context_messages, record["profile"], record["working_directory"])
        model_history = [ChatMessage.model_validate(item) for item in store.model_messages(conversation_id)]
        provider: ModelProvider = pick_provider(record["provider"], ollama, openai, anthropic)

        turn = await agent.resume_after_decision(
            provider,
            record["model"],
            [context.system_message, runtime_message(provider, record["model"]), *model_history],
            call=call,
            result_payload=outcome,
            workspace=workspace,
            logs_dir=settings.resolved_logs_dir(),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (StorageError, ContextError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if turn.pending_tool_call is not None:
        new_call = turn.pending_tool_call
        risk = tool_impl.RISK_BY_TOOL.get(new_call.name, "medium")
        new_record = store.create_pending_tool_call(
            conversation_id,
            new_call.id,
            new_call.name,
            new_call.arguments,
            risk,
            record["provider"],
            turn.resolved_model,
            record["profile"],
            record["working_directory"],
        )
        conversation, assistant_message = store.append_assistant_message(
            conversation_id,
            _tool_proposal_text(new_call),
            tool_call_id=new_call.id,
        )
        return ToolCallDecisionResponse(
            conversation=conversation,
            assistant_message=assistant_message,
            pending_tool_call=PendingToolCall(
                id=new_record["id"],
                tool_name=new_record["tool_name"],
                arguments=new_record["arguments"],
                risk_level=new_record["risk_level"],
                status=new_record["status"],
                created_at=new_record["created_at"],
            ),
        )

    conversation, assistant_message = store.append_assistant_message(conversation_id, turn.message.content)
    return ToolCallDecisionResponse(conversation=conversation, assistant_message=assistant_message)


@app.get("/api/attachments/{filename}", response_class=FileResponse)
def get_attachment(
    filename: str,
    store: ConversationStore = Depends(get_conversation_store),
) -> FileResponse:
    try:
        path = store.attachment_path(filename)
    except (NotFoundError, StorageError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)
