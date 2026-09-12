import base64
import binascii

import httpx

from samida.providers.base import ChatTurnResult, ModelProvider, ProviderError, ToolCallRequest
from samida.schemas import ChatMessage, UsageInfo

_API_VERSION = "2023-06-01"

_IMAGE_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
]


def _image_media_type(raw_base64: str) -> str:
    try:
        payload = base64.b64decode(raw_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProviderError("The image contains invalid base64 data.") from exc
    for signature, media_type in _IMAGE_SIGNATURES:
        if payload.startswith(signature):
            return media_type
    raise ProviderError("Could not identify the image format (supports PNG/JPEG/WebP).")


def _format_tools(specs: list[dict]) -> list[dict]:
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec["parameters"],
        }
        for spec in specs
    ]


def _message_payload(message: ChatMessage) -> dict:
    if message.role == "assistant" and message.tool_call_id:
        return {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": message.tool_call_id,
                    "name": message.tool_name,
                    "input": message.tool_arguments or {},
                }
            ],
        }
    if message.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
            ],
        }
    content: list[dict] = []
    if message.content:
        content.append({"type": "text", "text": message.content})
    content.extend(
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _image_media_type(image),
                "data": image,
            },
        }
        for image in message.images
    )
    return {"role": message.role, "content": content}


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, base_url: str, default_model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self.last_usage: UsageInfo | None = None

    async def model_names(self) -> list[str]:
        if not self.api_key:
            return []
        return list(dict.fromkeys([self.default_model, "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]))

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> ChatTurnResult:
        if not self.api_key:
            raise ProviderError("Anthropic is not configured yet.")

        resolved_model = model or self.default_model
        system_text = "\n\n".join(
            message.content for message in messages if message.role == "system" and message.content
        )
        payload = {
            "model": resolved_model,
            "max_tokens": 8192,
            "messages": [_message_payload(message) for message in messages if message.role != "system"],
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = _format_tools(tools)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": _API_VERSION,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(f"Anthropic rejected the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Anthropic could not be reached.") from exc

        data = response.json()
        raw_usage = data.get("usage")
        if isinstance(raw_usage, dict) and "input_tokens" in raw_usage and "output_tokens" in raw_usage:
            self.last_usage = UsageInfo(
                input_tokens=raw_usage["input_tokens"],
                output_tokens=raw_usage["output_tokens"],
                total_tokens=raw_usage["input_tokens"] + raw_usage["output_tokens"],
            )
        else:
            self.last_usage = None

        blocks = data.get("content", [])
        tool_use = next((block for block in blocks if block.get("type") == "tool_use"), None)
        if tool_use is not None:
            tool_call = ToolCallRequest(
                id=tool_use["id"],
                name=tool_use["name"],
                arguments=tool_use.get("input") or {},
            )
            return ChatTurnResult(resolved_model=resolved_model, tool_call=tool_call)

        content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not content.strip():
            raise ProviderError("Anthropic returned no text response.")

        return ChatTurnResult(
            resolved_model=resolved_model,
            message=ChatMessage(role="assistant", content=content),
        )
