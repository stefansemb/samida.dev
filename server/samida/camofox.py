from __future__ import annotations
from urllib.parse import urlparse
import httpx

class CamoFoxError(RuntimeError):
    """CamoFox is unavailable or the URL is not allowed."""

class CamoFoxClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    @staticmethod
    def _public_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise CamoFoxError("CamoFox får endast läsa offentliga HTTPS-sidor.")
        return url

    async def snapshot(self, url: str, *, user_id: str = "samida-research") -> str:
        url = self._public_url(url)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            tab_id: str | None = None
            try:
                response = await client.post("/tabs", json={"userId": user_id, "sessionKey": "research", "url": url})
                response.raise_for_status()
                data = response.json()
                tab_id = str(data.get("tabId") or data.get("id"))
                if tab_id == "None": raise CamoFoxError("CamoFox returnerade inget tab-id.")
                snapshot = await client.get(f"/tabs/{tab_id}/snapshot", params={"userId": user_id})
                snapshot.raise_for_status()
                payload = snapshot.json()
                return str(payload.get("snapshot") or payload.get("text") or payload)
            except (httpx.HTTPError, ValueError) as exc:
                raise CamoFoxError(f"CamoFox kunde inte läsa sidan: {exc}") from exc
            finally:
                if tab_id:
                    try: await client.delete(f"/tabs/{tab_id}", params={"userId": user_id})
                    except httpx.HTTPError: pass
