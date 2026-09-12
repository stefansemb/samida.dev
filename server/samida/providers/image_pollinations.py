import urllib.parse

import httpx

from samida.providers.base import ProviderError
from samida.providers.image_base import ImageGenerationResult, ImageProvider

# The old anonymous endpoint — free, no key, but watermarks its output.
_FREE_BASE_URL = "https://image.pollinations.ai"
# Pollinations' current official API. Requires a user's own sk_/pk_ key but
# doesn't watermark authenticated requests.
_AUTHENTICATED_BASE_URL = "https://gen.pollinations.ai"


class PollinationsProvider(ImageProvider):
    """Pollinations.ai. Used as the automatic fallback when a user hasn't
    configured a paid image provider, so generate_image always works out of
    the box: free and keyless (watermarked) by default, or watermark-free
    once the user adds their own free Pollinations API key."""

    name = "pollinations"

    def __init__(self, api_key: str | None, base_url: str, default_model: str, timeout: float) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        width, height = self._parse_size(size)
        encoded_prompt = urllib.parse.quote(prompt, safe="")
        params = {"model": self.default_model, "width": width, "height": height}
        headers: dict[str, str] = {}

        if self.api_key:
            base_url = _AUTHENTICATED_BASE_URL
            path = f"/image/{encoded_prompt}"
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            base_url = _FREE_BASE_URL
            path = f"/prompt/{encoded_prompt}"
            params["nologo"] = "true"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(f"{base_url}{path}", params=params, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Pollinations rejected the request: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Pollinations could not be reached.") from exc

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            raise ProviderError("Pollinations did not return an image.")
        return ImageGenerationResult(image_bytes=response.content, mime_type=content_type)

    @staticmethod
    def _parse_size(size: str | None) -> tuple[int, int]:
        if size and "x" in size.lower():
            try:
                width_str, height_str = size.lower().split("x", 1)
                return int(width_str), int(height_str)
            except ValueError:
                pass
        return 1024, 1024
