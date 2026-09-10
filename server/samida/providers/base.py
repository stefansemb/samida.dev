from abc import ABC, abstractmethod

from samida.schemas import ChatMessage, UsageInfo


class ProviderError(RuntimeError):
    """A safe, provider-level failure suitable for API error handling."""


class ModelProvider(ABC):
    name: str
    last_usage: UsageInfo | None = None

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> tuple[str, ChatMessage]:
        """Return the resolved model name and assistant response."""

    @abstractmethod
    async def model_names(self) -> list[str]:
        """Return model names currently available from the provider."""
