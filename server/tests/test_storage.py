import base64
from pathlib import Path

import pytest

from samida.schemas import ImageAttachment
from samida.storage import ConversationStore, NotFoundError


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "samida.db", tmp_path / "attachments")


def test_conversation_lifecycle(store: ConversationStore) -> None:
    conversation = store.create_conversation()
    assert conversation["title"] == "Ny chatt"

    renamed = store.rename_conversation(conversation["id"], "Unreal-frågor")
    assert renamed["title"] == "Unreal-frågor"

    store.delete_conversation(conversation["id"])
    with pytest.raises(NotFoundError):
        store.get_conversation(conversation["id"])


def test_exchange_creates_title_and_messages(store: ConversationStore) -> None:
    conversation = store.create_conversation()
    updated, user_message, assistant_message = store.add_exchange(
        conversation["id"], "Hjälp med Pirate Survival", "Absolut.", None
    )

    assert updated["title"] == "Hjälp med Pirate Survival"
    assert user_message["role"] == "user"
    assert assistant_message["role"] == "assistant"
    assert len(store.messages(conversation["id"])) == 2


def test_png_is_stored_and_deleted_with_conversation(
    store: ConversationStore,
) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"test"
    filename, encoded = store.save_image(
        ImageAttachment(
            filename="clipboard.png",
            mime_type="image/png",
            data_base64=base64.b64encode(png).decode("ascii"),
        )
    )
    conversation = store.create_conversation()
    store.add_exchange(conversation["id"], "", "Jag ser bilden.", filename)

    assert encoded
    assert store.attachment_path(filename).is_file()
    store.delete_conversation(conversation["id"])
    assert not (store.attachments_dir / filename).exists()


def test_research_reports_are_stored_and_filtered_by_type(store: ConversationStore) -> None:
    ai_report = store.create_research_report("AI", ["https://example.com/ai"], "ai_general")
    mobile_report = store.create_research_report(
        "Appar", ["https://example.com/apps"], "mobile_apps"
    )

    assert ai_report["research_type"] == "ai_general"
    assert mobile_report["title"] == "Mobilappar & trender"
    assert [item["id"] for item in store.list_research_reports("mobile_apps")] == [
        mobile_report["id"]
    ]
    assert [item["id"] for item in store.list_research_reports("ai_general")] == [
        ai_report["id"]
    ]


def test_existing_research_reports_are_migrated_to_ai_general(tmp_path: Path) -> None:
    import json
    import sqlite3

    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE research_reports (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
            "title TEXT NOT NULL, content TEXT NOT NULL, sources_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO research_reports VALUES (?, ?, ?, ?, ?)",
            ("old", "2026-09-01T00:00:00+00:00", "AI-omvärldsbevakning", "text", json.dumps([])),
        )

    migrated = ConversationStore(database, tmp_path / "attachments")

    assert migrated.list_research_reports("ai_general")[0]["research_type"] == "ai_general"


def test_research_report_idempotency_key_returns_existing_report(store: ConversationStore) -> None:
    first = store.create_research_report("first", [], "mobile_apps", "weekly-1")
    retry = store.create_research_report("second", [], "mobile_apps", "weekly-1")

    assert retry["id"] == first["id"]
    assert retry["content"] == "first"
    assert len(store.list_research_reports("mobile_apps")) == 1


def test_pending_tool_call_lifecycle(store: ConversationStore) -> None:
    conversation = store.create_conversation()
    created = store.create_pending_tool_call(
        conversation["id"],
        "call-1",
        "write_file",
        {"path": "notes.md", "content": "hej"},
        "medium",
        "openai",
        "gpt-5.6-terra",
        "minimal",
        "C:\\AiProjects\\WebchatDesign",
    )
    assert created["status"] == "pending"
    assert created["arguments"]["path"] == "notes.md"

    fetched = store.get_tool_call("call-1")
    assert fetched["tool_name"] == "write_file"

    resolved = store.resolve_tool_call("call-1", "executed", {"bytes_written": 3})
    assert resolved["status"] == "executed"
    assert resolved["result"] == {"bytes_written": 3}

    with pytest.raises(NotFoundError):
        store.resolve_tool_call("call-1", "executed", {})


def test_messages_expose_tool_call_placeholder(store: ConversationStore) -> None:
    conversation = store.create_conversation()
    store.create_pending_tool_call(
        conversation["id"],
        "call-2",
        "write_file",
        {"path": "a.txt", "content": "x"},
        "medium",
        "ollama",
        "gemma4:e4b",
        "minimal",
        "C:\\AiProjects\\WebchatDesign",
    )
    store.add_exchange(
        conversation["id"],
        "Skriv en fil",
        "Föreslår att skriva a.txt",
        None,
        assistant_tool_call_id="call-2",
    )

    messages = store.messages(conversation["id"])
    assistant_message = next(m for m in messages if m["role"] == "assistant")
    assert assistant_message["tool_call"]["id"] == "call-2"
    assert assistant_message["tool_call"]["status"] == "pending"

    user_message = next(m for m in messages if m["role"] == "user")
    assert user_message["tool_call"] is None
