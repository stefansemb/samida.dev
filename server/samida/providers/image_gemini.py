import base64

import httpx

from samida.providers.base import ProviderError
from samida.providers.image_base import ImageGenerationResult, ImageProvider


class NanoBananaProvider(ImageProvider):
    """Google Gemini image generation (nicknamed "Nano Banana")."""

    name = "nano_banana"

    def __init__(self, api_key: str | None, base_url: str, default_model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        if not self.api_key:
            raise ProviderError("Gemini (Nano Banana) is not configured.")
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/models/{self.default_model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gemini rejected the request: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Gemini could not be reached.") from exc

        data = response.json()
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return ImageGenerationResult(
                        image_bytes=base64.b64decode(inline["data"]),
                        mime_type=inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    )
        raise ProviderError("Gemini returned no image.")
