import base64
import binascii
import json

import httpx

from samida.providers.base import ChatTurnResult, ModelProvider, ProviderError, ToolCallRequest
from samida.schemas import ChatMessage, UsageInfo

_IMAGE_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
]


def _as_data_uri(raw_base64: str) -> str:
    """Ollama wants bare base64; OpenAI's image_url needs a full data URI."""
    try:
        payload = base64.b64decode(raw_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProviderError("The image contains invalid base64 data.") from exc
    for signature, mime_type in _IMAGE_SIGNATURES:
        if payload.startswith(signature):
            return f"data:{mime_type};base64,{raw_base64}"
    raise ProviderError("Could not identify the image format (supports PNG/JPEG/WebP).")


def _format_tools(specs: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": spec["name"],
            "description": spec["description"],
            "parameters": spec["parameters"],
        }
        for spec in specs
    ]


class OpenAIProvider(ModelProvider):
    name = "openai"

    def __init__(self, api_key: str | None, base_url: str, default_model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self.last_usage: UsageInfo | None = None

    async def model_names(self) -> list[str]:
        return [self.default_model, "gpt-5.6-terra", "gpt-5.6-sol"] if self.api_key else []

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> ChatTurnResult:
        if not self.api_key:
            raise ProviderError("OpenAI is not configured yet.")

        resolved_model = model or self.default_model
        payload = {
            "model": resolved_model,
            "input": [self._message_payload(message) for message in messages],
            "store": False,
        }
        if tools:
            payload["tools"] = _format_tools(tools)
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/responses",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(f"OpenAI rejected the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("OpenAI could not be reached.") from exc

        data = response.json()
        raw_usage = data.get("usage")
        self.last_usage = (
            UsageInfo(
                input_tokens=raw_usage["input_tokens"],
                output_tokens=raw_usage["output_tokens"],
                total_tokens=raw_usage["total_tokens"],
            )
            if isinstance(raw_usage, dict)
            and all(key in raw_usage for key in ("input_tokens", "output_tokens", "total_tokens"))
            else None
        )

        output = data.get("output", [])
        function_call = next((item for item in output if item.get("type") == "function_call"), None)
        if function_call is not None:
            try:
                arguments = json.loads(function_call.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError("OpenAI returned invalid tool arguments.") from exc
            tool_call = ToolCallRequest(
                id=function_call["call_id"],
                name=function_call["name"],
                arguments=arguments,
            )
            return ChatTurnResult(resolved_model=resolved_model, tool_call=tool_call)

        content = data.get("output_text")
        if not isinstance(content, str):
            content = "".join(
                item.get("text", "")
                for output_item in output
                for item in output_item.get("content", [])
                if item.get("type") == "output_text"
            )
        if not content.strip():
            raise ProviderError("OpenAI returned no text response.")

        return ChatTurnResult(
            resolved_model=resolved_model,
            message=ChatMessage(role="assistant", content=content),
        )

    @staticmethod
    def _message_payload(message: ChatMessage) -> dict:
        if message.role == "assistant" and message.tool_call_id:
            return {
                "type": "function_call",
                "call_id": message.tool_call_id,
                "name": message.tool_name,
                "arguments": json.dumps(message.tool_arguments or {}),
            }
        if message.role == "tool":
            return {
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": message.content,
            }
        text_type = "output_text" if message.role == "assistant" else "input_text"
        content: list[dict] = [{"type": text_type, "text": message.content}]
        content.extend(
            {"type": "input_image", "image_url": _as_data_uri(image)}
            for image in message.images
        )
        return {"role": message.role, "content": content}
