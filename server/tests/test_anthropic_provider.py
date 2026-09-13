from samida.providers.anthropic import _message_payload
from samida.schemas import ChatMessage

# A minimal valid 1x1 PNG, base64-encoded - enough to pass _image_media_type's
# signature check without needing a real image fixture.
_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_user_message_with_image_includes_image_block() -> None:
    message = ChatMessage(role="user", content="What's in this?", images=[_PNG_BASE64])

    payload = _message_payload(message)

    assert payload["role"] == "user"
    types = [item["type"] for item in payload["content"]]
    assert types == ["text", "image"]


def test_assistant_message_with_image_drops_the_image_block() -> None:
    """Regression test: a prior assistant turn can carry .images when reloaded
    from storage (e.g. a generate_image result re-attached on conversation
    reload - see storage.py's model_messages()). The Messages API rejects
    'image' content blocks on assistant-role turns entirely, so replaying one
    there 400s with "'image' blocks are not permitted within assistant
    turns." the moment a second image is requested in the same conversation."""
    message = ChatMessage(role="assistant", content="Here's your image.", images=[_PNG_BASE64])

    payload = _message_payload(message)

    assert payload["role"] == "assistant"
    types = [item["type"] for item in payload["content"]]
    assert types == ["text"]
