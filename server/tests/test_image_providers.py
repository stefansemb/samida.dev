import base64
import json

import httpx
import pytest

from samida import agent
from samida.providers.base import ProviderError
from samida.providers.image_base import ImageGenerationResult
from samida.providers.image_flux import FluxProvider
from samida.providers.image_gemini import NanoBananaProvider
from samida.providers.image_openai import GptImageProvider
from samida.providers.image_pollinations import PollinationsProvider

TINY_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\ntest-bytes").decode("ascii")


def _mock_client(monkeypatch, module, handler) -> None:
    real_async_client = httpx.AsyncClient  # capture before patching to avoid self-recursion

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_gpt_image_provider_parses_b64_response(monkeypatch) -> None:
    from samida.providers import image_openai

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["prompt"] == "en drake"
        return httpx.Response(200, json={"data": [{"b64_json": TINY_PNG, "revised_prompt": "en röd drake"}]})

    _mock_client(monkeypatch, image_openai, handler)
    provider = GptImageProvider(api_key="sk-test", base_url="https://api.openai.com/v1", default_model="gpt-image-1", timeout=5.0)

    result = await provider.generate("en drake")

    assert isinstance(result, ImageGenerationResult)
    assert result.image_bytes == base64.b64decode(TINY_PNG)
    assert result.mime_type == "image/png"
    assert result.revised_prompt == "en röd drake"


@pytest.mark.asyncio
async def test_gpt_image_provider_raises_without_key() -> None:
    provider = GptImageProvider(api_key=None, base_url="https://api.openai.com/v1", default_model="gpt-image-1", timeout=5.0)
    with pytest.raises(ProviderError):
        await provider.generate("en drake")


@pytest.mark.asyncio
async def test_gpt_image_provider_wraps_http_errors(monkeypatch) -> None:
    from samida.providers import image_openai

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    _mock_client(monkeypatch, image_openai, handler)
    provider = GptImageProvider(api_key="sk-bad", base_url="https://api.openai.com/v1", default_model="gpt-image-1", timeout=5.0)

    with pytest.raises(ProviderError):
        await provider.generate("en drake")


@pytest.mark.asyncio
async def test_flux_provider_submits_polls_and_fetches_image(monkeypatch) -> None:
    from samida.providers import image_flux

    image_flux._POLL_INTERVAL_SECONDS = 0  # skip the real sleep in tests
    calls = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/flux-pro-1.1":
            assert request.headers["x-key"] == "flux-test-key"
            return httpx.Response(200, json={"polling_url": "https://api.bfl.ai/poll/abc"})
        if request.url.path == "/poll/abc":
            calls["polls"] += 1
            if calls["polls"] < 2:
                return httpx.Response(200, json={"status": "Pending"})
            return httpx.Response(200, json={"status": "Ready", "result": {"sample": "https://delivery.bfl.ai/img.jpg"}})
        if request.url.path == "/img.jpg":
            return httpx.Response(200, content=b"fake-jpeg-bytes", headers={"content-type": "image/jpeg"})
        raise AssertionError(f"unexpected request to {request.url}")

    _mock_client(monkeypatch, image_flux, handler)
    provider = FluxProvider(api_key="flux-test-key", base_url="https://api.bfl.ai", default_model="flux-pro-1.1", timeout=5.0)

    result = await provider.generate("en drake", size="512x512")

    assert result.image_bytes == b"fake-jpeg-bytes"
    assert result.mime_type == "image/jpeg"
    assert calls["polls"] == 2


@pytest.mark.asyncio
async def test_flux_provider_raises_on_terminal_failure_status(monkeypatch) -> None:
    from samida.providers import image_flux

    image_flux._POLL_INTERVAL_SECONDS = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/"):
            return httpx.Response(200, json={"polling_url": "https://api.bfl.ai/poll/xyz"})
        return httpx.Response(200, json={"status": "Error"})

    _mock_client(monkeypatch, image_flux, handler)
    provider = FluxProvider(api_key="flux-test-key", base_url="https://api.bfl.ai", default_model="flux-pro-1.1", timeout=5.0)

    with pytest.raises(ProviderError):
        await provider.generate("en drake")


@pytest.mark.asyncio
async def test_nano_banana_provider_parses_inline_data(monkeypatch) -> None:
    from samida.providers import image_gemini

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "gem-test-key"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": TINY_PNG}}]}}
                ]
            },
        )

    _mock_client(monkeypatch, image_gemini, handler)
    provider = NanoBananaProvider(
        api_key="gem-test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.5-flash-image",
        timeout=5.0,
    )

    result = await provider.generate("en drake")

    assert result.image_bytes == base64.b64decode(TINY_PNG)
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_nano_banana_provider_raises_when_no_image_part(monkeypatch) -> None:
    from samida.providers import image_gemini

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "no image, sorry"}]}}]})

    _mock_client(monkeypatch, image_gemini, handler)
    provider = NanoBananaProvider(
        api_key="gem-test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.5-flash-image",
        timeout=5.0,
    )

    with pytest.raises(ProviderError):
        await provider.generate("en drake")


@pytest.mark.asyncio
async def test_pollinations_provider_needs_no_api_key(monkeypatch) -> None:
    from samida.providers import image_pollinations

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prompt/en drake"
        assert request.url.params["model"] == "flux"
        return httpx.Response(200, content=b"fake-jpeg-bytes", headers={"content-type": "image/jpeg"})

    _mock_client(monkeypatch, image_pollinations, handler)
    provider = PollinationsProvider(api_key=None, base_url="https://image.pollinations.ai", default_model="flux", timeout=5.0)

    result = await provider.generate("en drake")

    assert result.image_bytes == b"fake-jpeg-bytes"
    assert result.mime_type == "image/jpeg"


@pytest.mark.asyncio
async def test_pollinations_provider_raises_on_non_image_response(monkeypatch) -> None:
    from samida.providers import image_pollinations

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not an image", headers={"content-type": "text/plain"})

    _mock_client(monkeypatch, image_pollinations, handler)
    provider = PollinationsProvider(api_key=None, base_url="https://image.pollinations.ai", default_model="flux", timeout=5.0)

    with pytest.raises(ProviderError):
        await provider.generate("en drake")


@pytest.mark.asyncio
async def test_pollinations_provider_uses_authenticated_endpoint_with_key(monkeypatch) -> None:
    from samida.providers import image_pollinations

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "gen.pollinations.ai"
        assert request.url.path == "/image/en drake"
        assert request.headers["authorization"] == "Bearer sk_test_key"
        assert "nologo" not in request.url.params
        return httpx.Response(200, content=b"fake-jpeg-bytes", headers={"content-type": "image/jpeg"})

    _mock_client(monkeypatch, image_pollinations, handler)
    provider = PollinationsProvider(api_key="sk_test_key", base_url="https://image.pollinations.ai", default_model="flux", timeout=5.0)

    result = await provider.generate("en drake")

    assert result.image_bytes == b"fake-jpeg-bytes"


class _FakeStore:
    def __init__(self) -> None:
        self.saved: list[tuple[bytes, str]] = []

    def save_generated_image(self, image_bytes: bytes, mime_type: str) -> str:
        self.saved.append((image_bytes, mime_type))
        return "generated-123.png"


class _FakeImageProvider:
    name = "gpt_image"

    def __init__(self, result: ImageGenerationResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        if self._error:
            raise self._error
        assert self._result is not None
        return self._result


@pytest.mark.asyncio
async def test_generate_image_tool_without_context_returns_friendly_error() -> None:
    outcome = await agent.generate_image_tool(None, "en drake")
    assert "error" in outcome
    assert "Settings" in outcome["error"]


@pytest.mark.asyncio
async def test_generate_image_tool_rejects_blank_prompt() -> None:
    store = _FakeStore()
    context = agent.ImageToolContext(providers=[(_FakeImageProvider(), "gpt_image")], store=store)
    outcome = await agent.generate_image_tool(context, "   ")
    assert "error" in outcome
    assert not store.saved


@pytest.mark.asyncio
async def test_generate_image_tool_saves_image_and_returns_filename() -> None:
    store = _FakeStore()
    provider = _FakeImageProvider(result=ImageGenerationResult(image_bytes=b"bytes", mime_type="image/png"))
    context = agent.ImageToolContext(providers=[(provider, "gpt_image")], store=store)

    outcome = await agent.generate_image_tool(context, "en drake")

    assert outcome == {"image_filename": "generated-123.png", "prompt": "en drake", "provider": "gpt_image"}
    assert store.saved == [(b"bytes", "image/png")]


@pytest.mark.asyncio
async def test_generate_image_tool_surfaces_provider_error_without_saving() -> None:
    store = _FakeStore()
    provider = _FakeImageProvider(error=ProviderError("nyckeln avvisades"))
    context = agent.ImageToolContext(providers=[(provider, "gpt_image")], store=store)

    outcome = await agent.generate_image_tool(context, "en drake")

    assert outcome == {"error": "nyckeln avvisades"}
    assert not store.saved


class _NoCredentialStore:
    def get_provider_credential(self, user_id, kind, provider_key):
        return None


@pytest.mark.asyncio
async def test_image_provider_factory_falls_back_to_pollinations_when_unconfigured() -> None:
    from samida.config import Settings
    from samida.dependencies import ImageProviderFactory

    factory = ImageProviderFactory("user-1", _NoCredentialStore(), Settings())

    chain = await factory.build_fallback_chain()

    assert [key for _, key in chain] == ["pollinations"]
    assert isinstance(chain[0][0], PollinationsProvider)


@pytest.mark.asyncio
async def test_image_provider_factory_orders_chain_by_preference_then_pollinations() -> None:
    from cryptography.fernet import Fernet

    from samida.config import Settings as _Settings
    from samida.crypto import encrypt_secret
    from samida.dependencies import ImageProviderFactory

    settings = _Settings(secret_key=Fernet.generate_key().decode())
    encrypted = encrypt_secret("k", settings)

    class _Store:
        def get_provider_credential(self, user_id, kind, provider_key):
            if provider_key in {"flux", "nano_banana"}:
                return {"api_key_encrypted": encrypted, "base_url_override": None, "default_model": None}
            return None

    factory = ImageProviderFactory("user-1", _Store(), settings)

    chain = await factory.build_fallback_chain()

    assert [key for _, key in chain] == ["flux", "nano_banana", "pollinations"]
