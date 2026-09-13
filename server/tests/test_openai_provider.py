from samida.providers.openai import OpenAIProvider
from samida.schemas import ChatMessage

# A minimal valid 1x1 PNG, base64-encoded - enough to pass _as_data_uri's
# signature check without needing a real image fixture.
_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_user_message_with_image_includes_input_image_block() -> None:
    message = ChatMessage(role="user", content="What's in this?", images=[_PNG_BASE64])

    payload = OpenAIProvider._message_payload(message)

    assert payload["role"] == "user"
    types = [item["type"] for item in payload["content"]]
    assert types == ["input_text", "input_image"]


def test_assistant_message_with_image_drops_the_image_block() -> None:
    """Regression test: a prior assistant turn can carry .images when reloaded
    from storage (e.g. a generate_image result re-attached on conversation
    reload - see storage.py's model_messages()). The Responses API only
    allows output_text/refusal content for assistant-role turns - sending
    input_image there is rejected with a 400 from OpenAI. Reproduced live:
    generating a second image in the same conversation 400'd until this was
    fixed to drop images on assistant-role turns instead of replaying them."""
    message = ChatMessage(role="assistant", content="Here's your image.", images=[_PNG_BASE64])

    payload = OpenAIProvider._message_payload(message)

    assert payload["role"] == "assistant"
    types = [item["type"] for item in payload["content"]]
    assert types == ["output_text"]
