from uuid import uuid4

import httpx

from samida.providers.base import ChatTurnResult, ModelProvider, ProviderError, ToolCallRequest
from samida.schemas import ChatMessage


def _format_tools(specs: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for spec in specs
    ]


def _message_payload(message: ChatMessage) -> dict:
    if message.role == "assistant" and message.tool_call_id:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": message.tool_name, "arguments": message.tool_arguments or {}}}
            ],
        }
    if message.role == "tool":
        return {"role": "tool", "content": message.content}
    return {
        "role": message.role,
        "content": message.content,
        **({"images": message.images} if message.images else {}),
    }


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
        tools: list[dict] | None = None,
    ) -> ChatTurnResult:
        resolved_model = model or self.default_model
        payload = {
            "model": resolved_model,
            "messages": [_message_payload(message) for message in messages],
            "stream": False,
            "think": False,
        }
        if tools:
            payload["tools"] = _format_tools(tools)

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

        message = response.json().get("message", {})
        tool_calls = message.get("tool_calls")
        if tool_calls:
            call = tool_calls[0]["function"]
            tool_call = ToolCallRequest(
                id=str(uuid4()),
                name=call["name"],
                arguments=call.get("arguments") or {},
            )
            return ChatTurnResult(resolved_model=resolved_model, tool_call=tool_call)

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Ollama returnerade inget textsvar.")

        return ChatTurnResult(
            resolved_model=resolved_model,
            message=ChatMessage(role="assistant", content=content),
        )
