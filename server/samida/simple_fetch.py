from html.parser import HTMLParser
from urllib.parse import urlparse

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


def _public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise SimpleFetchError("Only public HTTPS pages can be fetched.")
    return url


async def fetch(url: str, *, timeout: float = 15.0) -> str:
    """Fetch a public HTTPS page with a plain HTTP request and strip it down
    to its visible text - no JavaScript execution, so it won't render
    client-side-only pages, but it costs nothing to ship (unlike a bundled
    browser) and handles the large majority of ordinary pages. Used as
    fetch_page's fallback when CamoFox (an optional, separately-run local
    service for JS-heavy or bot-guarded pages) isn't configured or reachable."""
    url = _public_url(url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; SAMIDA/1.0)"}
            )
            response.raise_for_status()
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
