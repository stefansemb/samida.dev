from functools import lru_cache

from samida.config import Settings, get_settings
from samida.context import ContextBuilder
from samida.camofox import CamoFoxClient
from samida.crypto import decrypt_secret
from samida.ocr import OcrService
from samida.providers import ImageProvider, ModelProvider, OllamaProvider, ProviderNotConfiguredError
from samida.providers.registry import CHAT_PROVIDER_SPECS, IMAGE_PROVIDER_PREFERENCE, IMAGE_PROVIDER_SPECS
from samida.search import SearchClient
from samida.storage import ConversationStore
from samida.weather import WeatherClient


@lru_cache
def get_ollama_provider() -> OllamaProvider:
    settings = get_settings()
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_chat_model,
        timeout=settings.request_timeout_seconds,
        api_key=settings.ollama_api_key,
    )


class ChatProviderFactory:
    """Builds a fresh chat provider per request, using the calling user's own
    stored (and decrypted) API key — providers hold a secret in memory, so
    they must never be cached/shared across users."""

    def __init__(self, user_id: str, store: ConversationStore, settings: Settings) -> None:
        self._user_id = user_id
        self._store = store
        self._settings = settings

    async def build(self, provider_key: str, requested_model: str | None) -> tuple[ModelProvider, str]:
        if provider_key == "ollama":
            provider = OllamaProvider(
                base_url=self._settings.ollama_base_url,
                default_model=self._settings.ollama_chat_model,
                timeout=self._settings.request_timeout_seconds,
                api_key=self._settings.ollama_api_key,
            )
            return provider, requested_model or self._settings.ollama_chat_model

        spec = CHAT_PROVIDER_SPECS.get(provider_key)
        if spec is None:
            raise ProviderNotConfiguredError(f"Unknown provider: {provider_key}.")
        credential = self._store.get_provider_credential(self._user_id, "chat", provider_key)
        if credential is None:
            raise ProviderNotConfiguredError(
                f"You haven't added an API key for {provider_key} under Settings."
            )
        api_key = decrypt_secret(credential["api_key_encrypted"], self._settings)
        default_model = credential["default_model"] or spec.default_model
        provider = spec.provider_class(
            api_key=api_key,
            base_url=credential["base_url_override"] or spec.default_base_url,
            default_model=default_model,
            timeout=self._settings.request_timeout_seconds,
        )
        return provider, requested_model or default_model


class ImageProviderFactory:
    """Builds the calling user's configured image-generation provider. Falls
    back to Pollinations.ai (free, keyless) when the user hasn't configured
    any of the paid providers, so generate_image always works."""

    def __init__(self, user_id: str, store: ConversationStore, settings: Settings) -> None:
        self._user_id = user_id
        self._store = store
        self._settings = settings

    async def build(self, provider_key: str) -> ImageProvider:
        spec = IMAGE_PROVIDER_SPECS.get(provider_key)
        if spec is None:
            raise ProviderNotConfiguredError(f"Unknown image provider: {provider_key}.")
        credential = self._store.get_provider_credential(self._user_id, "image", provider_key)
        if credential is None:
            if provider_key == "pollinations":
                # Free and keyless — works anonymously (with a watermark) if
                # the user hasn't optionally added their own free token.
                return spec.provider_class(
                    api_key=None,
                    base_url=spec.default_base_url,
                    default_model=spec.default_model,
                    timeout=self._settings.request_timeout_seconds,
                )
            raise ProviderNotConfiguredError(
                f"You haven't added an API key for {provider_key} under Settings."
            )
        api_key = decrypt_secret(credential["api_key_encrypted"], self._settings)
        return spec.provider_class(
            api_key=api_key,
            base_url=credential["base_url_override"] or spec.default_base_url,
            default_model=credential["default_model"] or spec.default_model,
            timeout=self._settings.request_timeout_seconds,
        )

    async def build_fallback_chain(self) -> list[tuple[ImageProvider, str]]:
        """The user's configured image providers, in preference order, with
        Pollinations.ai always appended last as the free/keyless guaranteed
        fallback. The generate_image tool tries each in turn so a quota or
        billing error from one paid provider doesn't fail the whole request."""
        chain: list[tuple[ImageProvider, str]] = []
        for provider_key in IMAGE_PROVIDER_PREFERENCE:
            credential = self._store.get_provider_credential(self._user_id, "image", provider_key)
            if credential is not None:
                chain.append((await self.build(provider_key), provider_key))
        chain.append((await self.build("pollinations"), "pollinations"))
        return chain


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


@lru_cache
def get_search_client() -> SearchClient:
    settings = get_settings()
    return SearchClient(settings.searxng_base_url, settings.request_timeout_seconds)


@lru_cache
def get_weather_client() -> WeatherClient:
    return WeatherClient(get_settings().request_timeout_seconds)
