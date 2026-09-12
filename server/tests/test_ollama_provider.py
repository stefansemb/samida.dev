import httpx
import pytest

from samida.providers import ollama as ollama_module
from samida.providers.ollama import OllamaProvider
from samida.schemas import ChatMessage


def _mock_client(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient  # capture before patching to avoid self-recursion

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(ollama_module.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_chat_sends_bearer_token_when_api_key_configured(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer cloud-test-key"
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hej"}})

    _mock_client(monkeypatch, handler)
    provider = OllamaProvider(
        base_url="https://ollama.com",
        default_model="gpt-oss:120b-cloud",
        timeout=5.0,
        api_key="cloud-test-key",
    )

    result = await provider.chat([ChatMessage(role="user", content="hej")])

    assert result.message is not None
    assert result.message.content == "hej"


@pytest.mark.asyncio
async def test_chat_omits_authorization_header_without_api_key(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hej"}})

    _mock_client(monkeypatch, handler)
    provider = OllamaProvider(
        base_url="http://localhost:11434",
        default_model="gemma4:e4b",
        timeout=5.0,
    )

    await provider.chat([ChatMessage(role="user", content="hej")])
