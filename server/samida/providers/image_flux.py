import asyncio

import httpx

from samida.providers.base import ProviderError
from samida.providers.image_base import ImageGenerationResult, ImageProvider

_POLL_INTERVAL_SECONDS = 1.0
_MAX_POLL_ATTEMPTS = 60
_TERMINAL_FAILURE_STATUSES = {"Error", "Failed", "Content Moderated", "Request Moderated"}


class FluxProvider(ImageProvider):
    """Black Forest Labs' Flux API — a submit-then-poll shape, unlike the
    single-request OpenAI/Gemini image APIs, hence its own provider class."""

    name = "flux"

    def __init__(self, api_key: str | None, base_url: str, default_model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        if not self.api_key:
            raise ProviderError("Flux (Black Forest Labs) is not configured.")
        width, height = self._parse_size(size)
        headers = {"x-key": self.api_key, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                submit = await client.post(
                    f"{self.base_url}/v1/{self.default_model}",
                    headers=headers,
                    json={"prompt": prompt, "width": width, "height": height},
                )
                submit.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderError(f"Flux rejected the request: {exc.response.text[:500]}") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("Flux could not be reached.") from exc

            polling_url = submit.json().get("polling_url")
            if not polling_url:
                raise ProviderError("Flux returned no polling ID.")

            for _ in range(_MAX_POLL_ATTEMPTS):
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                try:
                    poll = await client.get(polling_url, headers=headers)
                    poll.raise_for_status()
                except httpx.HTTPError as exc:
                    raise ProviderError("Flux could not be reached while polling.") from exc

                status_payload = poll.json()
                status = status_payload.get("status")
                if status == "Ready":
                    image_url = (status_payload.get("result") or {}).get("sample")
                    if not image_url:
                        raise ProviderError("Flux finished but returned no image URL.")
                    try:
                        image_response = await client.get(image_url)
                        image_response.raise_for_status()
                    except httpx.HTTPError as exc:
                        raise ProviderError("Could not fetch the generated image from Flux.") from exc
                    return ImageGenerationResult(
                        image_bytes=image_response.content,
                        mime_type=image_response.headers.get("content-type", "image/jpeg").split(";")[0],
                    )
                if status in _TERMINAL_FAILURE_STATUSES:
                    raise ProviderError(f"Flux failed: {status}")

        raise ProviderError("Flux did not respond in time.")

    @staticmethod
    def _parse_size(size: str | None) -> tuple[int, int]:
        if size and "x" in size.lower():
            try:
                width_str, height_str = size.lower().split("x", 1)
                return int(width_str), int(height_str)
            except ValueError:
                pass
        return 1024, 1024
