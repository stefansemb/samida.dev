import httpx
import pytest

from samida import simple_fetch as simple_fetch_module
from samida.simple_fetch import SimpleFetchError, fetch


def _mock_client(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient  # capture before patching to avoid self-recursion

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(simple_fetch_module.httpx, "AsyncClient", factory)


def _mock_resolver(monkeypatch, ip_by_host: dict[str, str]) -> None:
    def fake_getaddrinfo(host, *args, **kwargs):
        try:
            ip = ip_by_host[host]
        except KeyError:
            raise AssertionError(f"Unexpected DNS lookup for host: {host}") from None
        return [(None, None, None, None, (ip, 0))]

    monkeypatch.setattr(simple_fetch_module.socket, "getaddrinfo", fake_getaddrinfo)


async def test_rejects_non_https_url() -> None:
    with pytest.raises(SimpleFetchError):
        await fetch("http://example.com")


async def test_rejects_url_with_credentials() -> None:
    with pytest.raises(SimpleFetchError):
        await fetch("https://user:pass@example.com")


async def test_rejects_hostname_resolving_to_a_private_ip(monkeypatch) -> None:
    _mock_resolver(monkeypatch, {"internal.example": "192.168.1.50"})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("The request must never reach the network for a private IP.")

    _mock_client(monkeypatch, handler)

    with pytest.raises(SimpleFetchError):
        await fetch("https://internal.example/admin")


@pytest.mark.parametrize(
    "private_ip",
    ["127.0.0.1", "169.254.169.254", "10.0.0.5", "::1", "::ffff:127.0.0.1"],
)
async def test_rejects_various_private_and_loopback_addresses(monkeypatch, private_ip: str) -> None:
    _mock_resolver(monkeypatch, {"trap.example": private_ip})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("The request must never reach the network for a private IP.")

    _mock_client(monkeypatch, handler)

    with pytest.raises(SimpleFetchError):
        await fetch("https://trap.example")


async def test_fetches_and_extracts_text_for_a_public_ip(monkeypatch) -> None:
    _mock_resolver(monkeypatch, {"public.example": "93.184.216.34"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><head><style>ignored</style></head><body><h1>Hello</h1></body></html>")

    _mock_client(monkeypatch, handler)

    text = await fetch("https://public.example")

    assert text == "Hello"


async def test_follows_a_redirect_to_a_public_address(monkeypatch) -> None:
    _mock_resolver(monkeypatch, {"start.example": "93.184.216.34", "end.example": "93.184.216.35"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example":
            return httpx.Response(302, headers={"location": "https://end.example/final"})
        return httpx.Response(200, text="<p>Landed</p>")

    _mock_client(monkeypatch, handler)

    text = await fetch("https://start.example")

    assert text == "Landed"


async def test_rejects_a_redirect_to_a_private_address(monkeypatch) -> None:
    _mock_resolver(monkeypatch, {"start.example": "93.184.216.34", "internal.example": "10.0.0.5"})
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "start.example":
            return httpx.Response(302, headers={"location": "https://internal.example/steal"})
        raise AssertionError("The redirect target must never actually be requested.")

    _mock_client(monkeypatch, handler)

    with pytest.raises(SimpleFetchError):
        await fetch("https://start.example")

    assert calls == ["start.example"]


async def test_raises_when_the_page_has_no_readable_text(monkeypatch) -> None:
    _mock_resolver(monkeypatch, {"empty.example": "93.184.216.34"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><script>var x = 1;</script></body></html>")

    _mock_client(monkeypatch, handler)

    with pytest.raises(SimpleFetchError):
        await fetch("https://empty.example")
