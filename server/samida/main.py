import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from samida import agent, auth, tools as tool_impl
from samida.config import Settings, get_settings
from samida.context import ContextBuilder, ContextError
from samida.crypto import CryptoError, encrypt_secret
from samida.dependencies import (
    ChatProviderFactory,
    ImageProviderFactory,
    get_context_builder,
    get_conversation_store,
    get_ocr_service,
    get_ollama_provider,
)
from samida.providers import ModelProvider, OllamaProvider, ProviderError, ProviderNotConfiguredError, ToolCallRequest
from samida.providers.registry import CHAT_PROVIDER_SPECS, IMAGE_PROVIDER_SPECS
from samida.ocr import OcrService
from samida.research import run_research
from samida.camofox import CamoFoxClient
from samida.dependencies import get_camofox_client, get_search_client, get_weather_client
from samida.search import SearchClient
from samida.weather import WeatherClient
from samida import google_integration
from samida.google_integration import GoogleIntegration, GoogleOAuthError
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
    GoogleIntegrationStatus,
    HealthResponse,
    ModelCatalogEntry,
    PendingToolCall,
    ProviderCredentialPublic,
    ProviderCredentialUpsert,
    StoredMessage,
    ResearchReport,
    Reminder, ReminderCreate,
    ToolCallDecisionResponse,
    UserPublic,
    LoginRequest,
    RegisterRequest,
    WorkspacePickResponse,
)
from samida.storage import ConversationStore, NotFoundError, StorageError


def get_chat_provider_factory(
    user: auth.User = Depends(auth.get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
) -> ChatProviderFactory:
    return ChatProviderFactory(user.id, store, settings)


def get_image_provider_factory(
    user: auth.User = Depends(auth.get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
) -> ImageProviderFactory:
    return ImageProviderFactory(user.id, store, settings)

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
        *get_settings().resolved_cors_origins(),
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

@app.post("/api/workspace/pick", response_model=WorkspacePickResponse)
def pick_workspace(user: auth.User = Depends(auth.get_current_user)) -> WorkspacePickResponse:
    """Open a local native folder picker. Desktop-only; unavailable on a headless server."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="The folder picker is only available on a desktop installation of SAMIDA.",
        ) from exc
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(title="Choose working directory") or None
    finally:
        root.destroy()
    return WorkspacePickResponse(path=path)


@app.post("/api/auth/register", response_model=UserPublic, status_code=201)
def register(
    request: RegisterRequest,
    response: Response,
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
) -> UserPublic:
    email = request.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if store.get_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail="This email address is already in use.")
    user = store.create_user(email, auth.hash_password(request.password))
    raw_token, expires_at = auth.issue_session(store, user["id"])
    auth.set_session_cookie(response, raw_token, expires_at, secure=settings.cookie_secure)
    return UserPublic(id=user["id"], email=user["email"], tier=user["tier"])


@app.post("/api/auth/login", response_model=UserPublic)
def login(
    request: LoginRequest,
    response: Response,
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
) -> UserPublic:
    email = request.email.strip().lower()
    user = store.get_user_by_email(email)
    if user is None or not auth.verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    raw_token, expires_at = auth.issue_session(store, user["id"])
    auth.set_session_cookie(response, raw_token, expires_at, secure=settings.cookie_secure)
    return UserPublic(id=user["id"], email=user["email"], tier=user["tier"])


@app.post("/api/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    raw_token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if raw_token:
        store.delete_session(auth.hash_token(raw_token))
    auth.clear_session_cookie(response)


@app.get("/api/auth/me", response_model=UserPublic)
def me(user: auth.User = Depends(auth.get_current_user)) -> UserPublic:
    return UserPublic(id=user.id, email=user.email, tier=user.tier)


@app.get("/api/settings/providers", response_model=list[ProviderCredentialPublic])
def list_provider_credentials(
    kind: Literal["chat", "image"] = "chat",
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> list[ProviderCredentialPublic]:
    rows = store.list_provider_credentials(user.id, kind)
    configured = {row["provider_key"]: row for row in rows}
    provider_keys = (CHAT_PROVIDER_SPECS if kind == "chat" else IMAGE_PROVIDER_SPECS).keys()
    return [
        ProviderCredentialPublic(
            provider_key=key,
            configured=key in configured,
            base_url_override=configured[key]["base_url_override"] if key in configured else None,
            default_model=configured[key]["default_model"] if key in configured else None,
            updated_at=configured[key]["updated_at"] if key in configured else None,
        )
        for key in provider_keys
    ]


@app.put("/api/settings/providers/{provider_key}", response_model=ProviderCredentialPublic)
def upsert_provider_credential(
    provider_key: str,
    request: ProviderCredentialUpsert,
    kind: Literal["chat", "image"] = "chat",
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> ProviderCredentialPublic:
    valid_keys = CHAT_PROVIDER_SPECS if kind == "chat" else IMAGE_PROVIDER_SPECS
    if provider_key not in valid_keys:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_key}.")
    try:
        encrypted = encrypt_secret(request.api_key, settings)
    except CryptoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    row = store.upsert_provider_credential(
        user.id, kind, provider_key, encrypted, request.base_url_override, request.default_model,
    )
    return ProviderCredentialPublic(
        provider_key=row["provider_key"],
        configured=True,
        base_url_override=row["base_url_override"],
        default_model=row["default_model"],
        updated_at=row["updated_at"],
    )


@app.delete("/api/settings/providers/{provider_key}", status_code=204)
def delete_provider_credential(
    provider_key: str,
    kind: Literal["chat", "image"] = "chat",
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> None:
    try:
        store.delete_provider_credential(user.id, kind, provider_key)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


GOOGLE_OAUTH_STATE_COOKIE = "samida_google_oauth_state"


def _google_redirect_uri(settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/integrations/google/callback"


@app.get("/api/integrations/google/status", response_model=GoogleIntegrationStatus)
def google_integration_status(
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> GoogleIntegrationStatus:
    return GoogleIntegrationStatus(
        connected=GoogleIntegration(store, settings, user.id).is_connected(),
        configured=bool(settings.google_client_id and settings.google_client_secret),
    )


@app.get("/api/integrations/google/connect")
def google_integration_connect(
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
):
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(status_code=400, detail="Google integration is not configured on this server.")
    state = secrets.token_urlsafe(24)
    auth_url = google_integration.build_auth_url(settings.google_client_id, _google_redirect_uri(settings), state)
    redirect = RedirectResponse(auth_url)
    redirect.set_cookie(
        GOOGLE_OAUTH_STATE_COOKIE, state, max_age=600, httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    return redirect


@app.get("/api/integrations/google/callback")
async def google_integration_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
):
    expected_state = request.cookies.get(GOOGLE_OAUTH_STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid or expired Google authorization request.")
    try:
        payload = await google_integration.exchange_code(
            settings.google_client_id, settings.google_client_secret, _google_redirect_uri(settings), code,
        )
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if "refresh_token" not in payload:
        raise HTTPException(
            status_code=400,
            detail="Google didn't return a refresh token. Disconnect any prior SAMIDA access at "
            "https://myaccount.google.com/permissions and try connecting again.",
        )
    expires_at = datetime.now(UTC) + timedelta(seconds=payload["expires_in"])
    store.save_oauth_connection(
        user.id,
        google_integration.PROVIDER,
        encrypt_secret(payload["access_token"], settings),
        encrypt_secret(payload["refresh_token"], settings),
        expires_at.isoformat(),
        payload.get("scope", ""),
    )
    redirect = RedirectResponse(f"{settings.public_base_url.rstrip('/')}/settings?google=connected")
    redirect.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE)
    return redirect


@app.delete("/api/integrations/google", status_code=204)
def google_integration_disconnect(
    store: ConversationStore = Depends(get_conversation_store),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> None:
    GoogleIntegration(store, settings, user.id).disconnect()


@app.get("/api/models/catalog", response_model=list[ModelCatalogEntry])
async def list_model_catalog(
    kind: Literal["chat", "image"] = "chat",
    store: ConversationStore = Depends(get_conversation_store),
    ollama: OllamaProvider = Depends(get_ollama_provider),
    user: auth.User = Depends(auth.get_current_user),
) -> list[ModelCatalogEntry]:
    configured_keys = {row["provider_key"] for row in store.list_provider_credentials(user.id, kind)}
    entries = [
        ModelCatalogEntry(
            provider_key=row["provider_key"],
            model_name=row["model_name"],
            display_name=row["display_name"],
            supports_vision=bool(row["supports_vision"]),
            supports_tools=bool(row["supports_tools"]),
            requires_user_key=bool(row["requires_user_key"]),
            usable=not row["requires_user_key"] or row["provider_key"] in configured_keys,
        )
        for row in store.list_model_catalog(kind)
    ]
    if kind == "chat":
        try:
            ollama_models = await ollama.model_names()
        except ProviderError:
            ollama_models = []
        for name in ollama_models:
            normalized = name.lower()
            if "cloud" in normalized or normalized.startswith("bge-"):
                continue
            entries.append(
                ModelCatalogEntry(
                    provider_key="ollama",
                    model_name=name,
                    display_name=name,
                    supports_vision=False,
                    supports_tools=True,
                    requires_user_key=False,
                    usable=True,
                )
            )
    return entries


def runtime_message(provider: ModelProvider, model: str) -> ChatMessage:
    return ChatMessage(
        role="system",
        content=(
            "Internal runtime information: this response is generated by "
            f"provider '{provider.name}' with model '{model}'. "
            "If the user asks which model is being used, state these "
            "values exactly and do not guess."
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
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
    context_builder: ContextBuilder = Depends(get_context_builder),
    factory: ChatProviderFactory = Depends(get_chat_provider_factory),
) -> ChatResponse:
    try:
        context = context_builder.build(request.messages, request.profile, request.working_directory)
        selected_model = request.model
        if selected_model is None and any(message.images for message in request.messages):
            selected_model = settings.ollama_vision_model
        provider, resolved_model = await factory.build(request.provider, selected_model)
        turn = await provider.chat(
            [context.system_message, runtime_message(provider, resolved_model), *request.messages],
            resolved_model,
        )
        if turn.message is None:
            raise ProviderError("The model attempted to call a tool, which is not supported here.")
    except ContextError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    user: auth.User = Depends(auth.get_current_user),
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
    user: auth.User = Depends(auth.get_current_user),
) -> list[dict]:
    return store.list_conversations(user.id)


@app.get("/api/research/reports", response_model=list[ResearchReport])
def list_research_reports(
    research_type: Literal["ai_general", "mobile_apps"] = "ai_general",
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> list[dict]:
    return store.list_research_reports(user.id, research_type)

@app.get("/api/reminders", response_model=list[Reminder])
def list_reminders(
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> list[dict]:
    return store.list_reminders(user.id)

@app.get("/api/priorities")
def get_priorities(
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> dict[str, str]:
    path = settings.project_root / "memory" / "priorities.md"
    return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}

@app.post("/api/reminders", response_model=Reminder, status_code=201)
def create_reminder(
    request: ReminderCreate,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> dict:
    return store.create_reminder(user.id, request.text, request.due_at, request.recurrence, request.range_start, request.range_end, request.event_at)

@app.post("/api/reminders/{reminder_id}/complete", status_code=204)
def complete_reminder(
    reminder_id: str,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> None:
    try:
        store.complete_reminder(reminder_id, user.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.delete("/api/reminders/{reminder_id}", status_code=204)
def delete_reminder(
    reminder_id: str,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> None:
    try:
        store.delete_reminder(reminder_id, user.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/research/run", response_model=ResearchReport, status_code=201)
async def create_research_report(
    research_type: Literal["ai_general", "mobile_apps"] = "ai_general",
    ollama: OllamaProvider = Depends(get_ollama_provider),
    settings: Settings = Depends(get_settings),
    store: ConversationStore = Depends(get_conversation_store),
    camofox: CamoFoxClient | None = Depends(get_camofox_client),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    user: auth.User = Depends(auth.get_current_user),
) -> dict:
    if idempotency_key:
        existing = store.get_research_report_by_idempotency_key(user.id, idempotency_key)
        if existing:
            return existing
    try:
        content, sources = await run_research(ollama, settings.ollama_chat_model, research_type, camofox)
        return store.create_research_report(user.id, content, sources, research_type, idempotency_key)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(
    request: ConversationCreate,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> dict:
    return store.create_conversation(user.id, request.title)


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> dict:
    try:
        conversation = store.get_conversation(conversation_id, user.id)
        return {**conversation, "messages": store.messages(conversation_id, user.id)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    request: ConversationRename,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> dict:
    try:
        return store.rename_conversation(conversation_id, user.id, request.title)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> None:
    try:
        store.delete_conversation(conversation_id, user.id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/api/conversations/{conversation_id}/chat",
    response_model=ConversationChatResponse,
)
async def conversation_chat(
    conversation_id: str,
    request: ConversationChatRequest,
    factory: ChatProviderFactory = Depends(get_chat_provider_factory),
    image_factory: ImageProviderFactory = Depends(get_image_provider_factory),
    context_builder: ContextBuilder = Depends(get_context_builder),
    store: ConversationStore = Depends(get_conversation_store),
    ocr: OcrService = Depends(get_ocr_service),
    search_client: SearchClient = Depends(get_search_client),
    camofox: CamoFoxClient | None = Depends(get_camofox_client),
    weather_client: WeatherClient = Depends(get_weather_client),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> ConversationChatResponse:
    image_filename = None
    image_base64 = None
    ocr_text = None
    try:
        store.get_conversation(conversation_id, user.id)
        if request.image:
            image_filename, image_base64 = store.save_image(request.image)
            ocr_text = await asyncio.to_thread(
                ocr.extract_text,
                store.attachment_path(image_filename),
            )
        history = [
            StoredMessage.model_validate(message)
            for message in store.messages(conversation_id, user.id)
        ]
        context_messages = [
            ChatMessage(
                role=message.role,
                content=message.content or "[Screenshot]",
            )
            for message in history
        ]
        current_content = request.content.strip() or "Describe and analyze the image."
        if ocr_text:
            current_content += (
                "\n\nA local OCR tool read the following text from the image. "
                "Use it as a reference and cross-check it against the image:\n---\n"
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
            for message in store.model_messages(conversation_id, user.id)
        ]
        selected_model = request.model
        if image_base64 and request.provider == "ollama":
            selected_model = settings.ollama_vision_model
        provider, resolved_model = await factory.build(request.provider, selected_model)
        workspace = _resolve_workspace(request.working_directory)
        image_providers = await image_factory.build_fallback_chain()
        image_context = agent.ImageToolContext(providers=image_providers, store=store)
        notes_context = agent.NotesToolContext(store=store, user_id=user.id)
        google_context = agent.GoogleToolContext(integration=GoogleIntegration(store, settings, user.id))
        turn = await agent.run_turn(
            provider,
            resolved_model,
            [
                context.system_message,
                runtime_message(provider, resolved_model),
                *model_history,
                current,
            ],
            workspace=workspace,
            logs_dir=settings.resolved_logs_dir(),
            image_context=image_context,
            search_client=search_client,
            camofox_client=camofox,
            weather_client=weather_client,
            notes_context=notes_context,
            google_context=google_context,
        )

        pending_tool_call: PendingToolCall | None = None
        if turn.pending_tool_call is not None:
            call = turn.pending_tool_call
            risk = tool_impl.RISK_BY_TOOL.get(call.name, "medium")
            record = store.create_pending_tool_call(
                conversation_id,
                user.id,
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
                user.id,
                request.content.strip(),
                _tool_proposal_text(call),
                image_filename,
                ocr_text,
                assistant_tool_call_id=call.id,
                assistant_image_filename=turn.image_filename,
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
                user.id,
                request.content.strip(),
                turn.message.content,
                image_filename,
                ocr_text,
                assistant_image_filename=turn.image_filename,
            )
    except NotFoundError as exc:
        if image_filename:
            store.attachment_path(image_filename).unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (StorageError, ContextError) as exc:
        if image_filename:
            store.attachment_path(image_filename).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
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
        return f'Proposing to write to "{path}" ({lines} lines). Waiting for your approval.'
    return f"Proposing to run the tool {call.name}. Waiting for your approval."


@app.post(
    "/api/conversations/{conversation_id}/tool-calls/{tool_call_id}/approve",
    response_model=ToolCallDecisionResponse,
)
async def approve_tool_call(
    conversation_id: str,
    tool_call_id: str,
    factory: ChatProviderFactory = Depends(get_chat_provider_factory),
    image_factory: ImageProviderFactory = Depends(get_image_provider_factory),
    context_builder: ContextBuilder = Depends(get_context_builder),
    store: ConversationStore = Depends(get_conversation_store),
    search_client: SearchClient = Depends(get_search_client),
    camofox: CamoFoxClient | None = Depends(get_camofox_client),
    weather_client: WeatherClient = Depends(get_weather_client),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> ToolCallDecisionResponse:
    return await _resolve_tool_call(
        conversation_id,
        tool_call_id,
        approve=True,
        factory=factory,
        image_factory=image_factory,
        context_builder=context_builder,
        store=store,
        search_client=search_client,
        camofox=camofox,
        weather_client=weather_client,
        settings=settings,
        owner_id=user.id,
    )


@app.post(
    "/api/conversations/{conversation_id}/tool-calls/{tool_call_id}/reject",
    response_model=ToolCallDecisionResponse,
)
async def reject_tool_call(
    conversation_id: str,
    tool_call_id: str,
    factory: ChatProviderFactory = Depends(get_chat_provider_factory),
    image_factory: ImageProviderFactory = Depends(get_image_provider_factory),
    context_builder: ContextBuilder = Depends(get_context_builder),
    store: ConversationStore = Depends(get_conversation_store),
    search_client: SearchClient = Depends(get_search_client),
    camofox: CamoFoxClient | None = Depends(get_camofox_client),
    weather_client: WeatherClient = Depends(get_weather_client),
    settings: Settings = Depends(get_settings),
    user: auth.User = Depends(auth.get_current_user),
) -> ToolCallDecisionResponse:
    return await _resolve_tool_call(
        conversation_id,
        tool_call_id,
        approve=False,
        factory=factory,
        image_factory=image_factory,
        context_builder=context_builder,
        store=store,
        search_client=search_client,
        camofox=camofox,
        weather_client=weather_client,
        settings=settings,
        owner_id=user.id,
    )


async def _resolve_tool_call(
    conversation_id: str,
    tool_call_id: str,
    *,
    approve: bool,
    factory: ChatProviderFactory,
    image_factory: ImageProviderFactory,
    context_builder: ContextBuilder,
    store: ConversationStore,
    search_client: SearchClient,
    camofox: CamoFoxClient | None,
    weather_client: WeatherClient,
    settings: Settings,
    owner_id: str,
) -> ToolCallDecisionResponse:
    try:
        record = store.get_tool_call(tool_call_id, owner_id)
        if record["conversation_id"] != conversation_id:
            raise NotFoundError("The tool call does not belong to this chat.")
        if record["status"] != "pending":
            raise StorageError("The tool call has already been resolved.")

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
            outcome = {"status": "rejected", "message": "The user rejected the action."}
            status = "rejected"
        tool_impl.log_tool_call(
            settings.resolved_logs_dir(),
            tool_name=call.name,
            target=target,
            risk_level=record["risk_level"],
            status=status,
            detail=str(outcome),
        )
        store.resolve_tool_call(tool_call_id, owner_id, status=status, result=outcome)

        history = [StoredMessage.model_validate(item) for item in store.messages(conversation_id, owner_id)]
        context_messages = [ChatMessage(role=item.role, content=item.content or "[Screenshot]") for item in history]
        context = context_builder.build(context_messages, record["profile"], record["working_directory"])
        model_history = [ChatMessage.model_validate(item) for item in store.model_messages(conversation_id, owner_id)]
        provider, _resolved = await factory.build(record["provider"], record["model"])
        image_providers = await image_factory.build_fallback_chain()
        image_context = agent.ImageToolContext(providers=image_providers, store=store)
        notes_context = agent.NotesToolContext(store=store, user_id=owner_id)
        google_context = agent.GoogleToolContext(integration=GoogleIntegration(store, settings, owner_id))

        turn = await agent.resume_after_decision(
            provider,
            record["model"],
            [context.system_message, runtime_message(provider, record["model"]), *model_history],
            call=call,
            result_payload=outcome,
            workspace=workspace,
            logs_dir=settings.resolved_logs_dir(),
            image_context=image_context,
            search_client=search_client,
            camofox_client=camofox,
            weather_client=weather_client,
            notes_context=notes_context,
            google_context=google_context,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (StorageError, ContextError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if turn.pending_tool_call is not None:
        new_call = turn.pending_tool_call
        risk = tool_impl.RISK_BY_TOOL.get(new_call.name, "medium")
        new_record = store.create_pending_tool_call(
            conversation_id,
            owner_id,
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
            owner_id,
            _tool_proposal_text(new_call),
            tool_call_id=new_call.id,
            image_filename=turn.image_filename,
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

    conversation, assistant_message = store.append_assistant_message(
        conversation_id, owner_id, turn.message.content, image_filename=turn.image_filename
    )
    return ToolCallDecisionResponse(conversation=conversation, assistant_message=assistant_message)


@app.get("/api/attachments/{filename}", response_class=FileResponse)
def get_attachment(
    filename: str,
    store: ConversationStore = Depends(get_conversation_store),
    user: auth.User = Depends(auth.get_current_user),
) -> FileResponse:
    try:
        path = store.attachment_path(filename)
    except (NotFoundError, StorageError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if store.attachment_owner_id(filename) != user.id:
        raise HTTPException(status_code=404, detail="The image does not exist.")
    return FileResponse(path)
