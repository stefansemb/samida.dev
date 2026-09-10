from functools import lru_cache

from samida.config import get_settings
from samida.context import ContextBuilder
from samida.camofox import CamoFoxClient
from samida.ocr import OcrService
from samida.providers import AnthropicProvider, OllamaProvider, OpenAIProvider
from samida.storage import ConversationStore


@lru_cache
def get_ollama_provider() -> OllamaProvider:
    settings = get_settings()
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_chat_model,
        timeout=settings.request_timeout_seconds,
    )


@lru_cache
def get_openai_provider() -> OpenAIProvider:
    settings = get_settings()
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        default_model=settings.openai_model,
        timeout=settings.request_timeout_seconds,
    )


@lru_cache
def get_anthropic_provider() -> AnthropicProvider:
    settings = get_settings()
    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
        default_model=settings.anthropic_model,
        timeout=settings.request_timeout_seconds,
    )


@lru_cache
def get_context_builder() -> ContextBuilder:
    return ContextBuilder(get_settings().project_root)


@lru_cache
def get_conversation_store() -> ConversationStore:
    settings = get_settings()
    return ConversationStore(
        settings.resolved_database_path(),
        settings.resolved_attachments_dir(),
    )


@lru_cache
def get_ocr_service() -> OcrService:
    return OcrService()

@lru_cache
def get_camofox_client() -> CamoFoxClient | None:
    settings = get_settings()
    return CamoFoxClient(settings.camofox_base_url, settings.request_timeout_seconds) if settings.camofox_enabled else None
