import base64

import httpx

from samida.providers.base import ProviderError
from samida.providers.image_base import ImageGenerationResult, ImageProvider


class GptImageProvider(ImageProvider):
    name = "gpt_image"

    def __init__(self, api_key: str | None, base_url: str, default_model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        if not self.api_key:
            raise ProviderError("OpenAI image generation is not configured.")
        payload = {
            "model": self.default_model,
            "prompt": prompt,
            "size": size or "1024x1024",
            "n": 1,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/images/generations",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(f"OpenAI (image) rejected the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("OpenAI (image) could not be reached.") from exc

        data = response.json()
        items = data.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise ProviderError("OpenAI returned no image.")
        image_bytes = base64.b64decode(items[0]["b64_json"])
        return ImageGenerationResult(
            image_bytes=image_bytes,
            mime_type="image/png",
            revised_prompt=items[0].get("revised_prompt"),
        )
