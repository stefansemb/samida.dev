from dataclasses import dataclass

import httpx


class SearchError(RuntimeError):
    """Web search is unavailable or returned no usable result."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchClient:
    """Queries a self-hosted SearxNG instance (a meta-search engine that
    aggregates Google/Bing/Brave/DuckDuckGo etc.), so web_search works the
    same way regardless of which chat model/provider answers the turn."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params={"q": query, "format": "json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchError("Web search could not be reached.") from exc

        payload = response.json()
        results = [
            SearchResult(
                title=str(item.get("title") or "").strip(),
                url=str(item.get("url") or "").strip(),
                snippet=str(item.get("content") or "").strip(),
            )
            for item in payload.get("results", [])
        ]
        return [item for item in results if item.title and item.url][:limit]
