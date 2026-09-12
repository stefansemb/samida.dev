from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class UserPublic(BaseModel):
    id: str
    email: str
    tier: str
    is_owner: bool = False


class ProviderCredentialUpsert(BaseModel):
    api_key: str = Field(min_length=1, max_length=2000)
    base_url_override: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=200)


class ProviderCredentialPublic(BaseModel):
    provider_key: str
    configured: bool
    base_url_override: str | None = None
    default_model: str | None = None
    updated_at: str | None = None


class GoogleIntegrationStatus(BaseModel):
    connected: bool
    configured: bool  # whether the server has Google OAuth client credentials at all


class ModelCatalogEntry(BaseModel):
    provider_key: str
    model_name: str
    display_name: str
    supports_vision: bool
    supports_tools: bool
    requires_user_key: bool
    usable: bool


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    images: list[str] = Field(default_factory=list, exclude=True)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict | None = None

    @model_validator(mode="after")
    def require_content_or_image(self) -> "ChatMessage":
        if self.tool_call_id:
            return self
        if not self.content.strip() and not self.images:
            raise ValueError("A message must contain text or an image.")
        return self


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    provider: str = "ollama"
    model: str | None = None
    profile: Literal["minimal", "samida-standard", "coding", "jarvis", "unreal"] = "minimal"
    working_directory: str | None = None


class UsageInfo(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    provider: str
    model: str
    message: ChatMessage
    context_files: list[str]
    usage: "UsageInfo | None" = None


class ContextPreviewRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


class ContextPreviewResponse(BaseModel):
    context_files: list[str]
    system_prompt: str

class WorkspacePickResponse(BaseModel):
    path: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama_reachable: bool
    configured_model: str
    model_available: bool
    configured_vision_model: str
    vision_model_available: bool
    available_models: list[str] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=120)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class PendingToolCall(BaseModel):
    id: str
    tool_name: str
    arguments: dict
    risk_level: Literal["low", "medium"]
    status: Literal["pending", "approved", "rejected", "executed", "failed"]
    created_at: str


class StoredMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    image_url: str | None
    ocr_text: str | None
    created_at: str
    tool_call: PendingToolCall | None = None


class ConversationDetail(ConversationSummary):
    messages: list[StoredMessage]


class ImageAttachment(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str = Field(min_length=1)


class ConversationChatRequest(BaseModel):
    content: str = Field(default="", max_length=50_000)
    image: ImageAttachment | None = None
    provider: str = "ollama"
    model: str | None = None
    profile: Literal["minimal", "samida-standard", "coding", "jarvis", "unreal"] = "minimal"
    working_directory: str | None = None

    @model_validator(mode="after")
    def require_text_or_image(self) -> "ConversationChatRequest":
        if not self.content.strip() and self.image is None:
            raise ValueError("The message must contain text or an image.")
        return self


class ConversationChatResponse(BaseModel):
    conversation: ConversationSummary
    user_message: StoredMessage
    assistant_message: StoredMessage
    provider: str
    model: str
    context_files: list[str]
    ocr_text: str | None
    usage: UsageInfo | None = None
    pending_tool_call: PendingToolCall | None = None


class ToolCallDecisionResponse(BaseModel):
    conversation: ConversationSummary
    assistant_message: StoredMessage
    pending_tool_call: PendingToolCall | None = None


class ResearchReport(BaseModel):
    id: str
    created_at: str
    title: str
    content: str
    sources: list[str] = Field(default_factory=list)
    research_type: Literal["ai_general", "mobile_apps"] = "ai_general"

class ReminderCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due_at: str
    event_at: str | None = None
    recurrence: Literal['once', 'daily', 'weekly', 'monthly', 'monthly_range'] = 'once'
    range_start: int | None = Field(default=None, ge=1, le=31)
    range_end: int | None = Field(default=None, ge=1, le=31)

class Reminder(ReminderCreate):
    id: str
    done: bool = False
    created_at: str
