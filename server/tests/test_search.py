import httpx
import pytest

from samida import search as search_module
from samida.search import SearchClient, SearchError


def _mock_client(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient  # capture before patching to avoid self-recursion

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(search_module.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_search_parses_and_limits_results(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["q"] == "vad ar samida"
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": "snippet"}
                    for i in range(8)
                ]
            },
        )

    _mock_client(monkeypatch, handler)
    client = SearchClient(base_url="http://127.0.0.1:8888", timeout=5.0)

    results = await client.search("vad ar samida")

    assert len(results) == 5
    assert results[0].title == "Result 0"
    assert results[0].url == "https://example.com/0"
    assert results[0].snippet == "snippet"


@pytest.mark.asyncio
async def test_search_skips_results_missing_title_or_url(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"title": "", "url": "https://example.com", "content": "x"}]},
        )

    _mock_client(monkeypatch, handler)
    client = SearchClient(base_url="http://127.0.0.1:8888", timeout=5.0)

    results = await client.search("query")

    assert results == []


@pytest.mark.asyncio
async def test_search_raises_search_error_when_unreachable(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    _mock_client(monkeypatch, handler)
    client = SearchClient(base_url="http://127.0.0.1:8888", timeout=5.0)

    with pytest.raises(SearchError):
        await client.search("query")
