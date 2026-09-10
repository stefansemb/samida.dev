from abc import ABC, abstractmethod
from dataclasses import dataclass

from samida.schemas import ChatMessage, UsageInfo


class ProviderError(RuntimeError):
    """A safe, provider-level failure suitable for API error handling."""


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatTurnResult:
    resolved_model: str
    message: ChatMessage | None = None
    tool_call: ToolCallRequest | None = None


class ModelProvider(ABC):
    name: str
    last_usage: UsageInfo | None = None

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> ChatTurnResult:
        """Run one model turn; returns either a final message or a proposed tool call."""

    @abstractmethod
    async def model_names(self) -> list[str]:
        """Return model names currently available from the provider."""
