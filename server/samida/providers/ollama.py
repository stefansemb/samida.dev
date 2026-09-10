import httpx

from samida.providers.base import ModelProvider, ProviderError
from samida.schemas import ChatMessage


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, base_url: str, default_model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def model_names(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError("Ollama kunde inte nås.") from exc

        models = response.json().get("models", [])
        return [item["name"] for item in models if "name" in item]

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> tuple[str, ChatMessage]:
        resolved_model = model or self.default_model
        payload = {
            "model": resolved_model,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    **({"images": message.images} if message.images else {}),
                }
                for message in messages
            ],
            "stream": False,
            "think": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(f"Ollama avvisade anropet: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Ollama kunde inte nås.") from exc

        content = response.json().get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Ollama returnerade inget textsvar.")

        return resolved_model, ChatMessage(role="assistant", content=content)
