import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx


class SimpleFetchError(RuntimeError):
    """A lightweight, browser-less page fetch failed or the URL isn't allowed."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = data.strip()
            if text:
                self.chunks.append(text)


def _is_public_ip(raw_ip: str) -> bool:
    address = ipaddress.ip_address(raw_ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _public_url(url: str) -> str:
    # This tool's URL comes from whatever page/prompt the model is reading -
    # a malicious page could try to get it to "fetch" an internal address
    # (a home-network device, a cloud metadata endpoint, localhost) instead
    # of a real public page. Scheme alone doesn't stop that, so resolve the
    # hostname and reject anything that lands on a private/internal IP.
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SimpleFetchError("Only public HTTPS pages can be fetched.")
    try:
        resolved_ips = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise SimpleFetchError(f"Could not resolve the page's hostname: {exc}") from exc
    if not resolved_ips or not all(_is_public_ip(ip) for ip in resolved_ips):
        raise SimpleFetchError("This URL resolves to a private or internal address, which can't be fetched.")
    return url


MAX_REDIRECTS = 5


async def fetch(url: str, *, timeout: float = 15.0) -> str:
    """Fetch a public HTTPS page with a plain HTTP request and strip it down
    to its visible text - no JavaScript execution, so it won't render
    client-side-only pages, but it costs nothing to ship (unlike a bundled
    browser) and handles the large majority of ordinary pages. Used as
    fetch_page's fallback when CamoFox (an optional, separately-run local
    service for JS-heavy or bot-guarded pages) isn't configured or reachable."""
    url = _public_url(url)
    try:
        # Redirects are followed manually (not httpx's follow_redirects) so
        # each hop is re-validated - otherwise a public URL could redirect
        # straight to an internal address and skip the check above entirely.
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            for _ in range(MAX_REDIRECTS + 1):
                response = await client.get(
                    url, headers={"User-Agent": "Mozilla/5.0 (compatible; SAMIDA/1.0)"}
                )
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise SimpleFetchError("The page redirected without a destination.")
                    url = _public_url(urljoin(str(response.url), location))
                    continue
                response.raise_for_status()
                break
            else:
                raise SimpleFetchError("The page redirected too many times.")
    except httpx.HTTPError as exc:
        raise SimpleFetchError(f"Could not fetch the page: {exc}") from exc

    parser = _TextExtractor()
    parser.feed(response.text)
    text = "\n".join(parser.chunks).strip()
    if not text:
        raise SimpleFetchError(
            "The page returned no readable text - it may require JavaScript to render."
        )
    return text
