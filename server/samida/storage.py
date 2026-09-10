import base64
import binascii
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from samida.schemas import ImageAttachment


class StorageError(RuntimeError):
    pass


class NotFoundError(StorageError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ConversationStore:
    def __init__(self, database_path: Path, attachments_dir: Path) -> None:
        self.database_path = database_path.resolve()
        self.attachments_dir = attachments_dir.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    image_filename TEXT,
                    ocr_text TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
                    ON conversations(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS research_reports (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    research_type TEXT NOT NULL DEFAULT 'ai_general',
                    idempotency_key TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_research_reports_created
                    ON research_reports(created_at DESC);
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY, text TEXT NOT NULL, due_at TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                PRAGMA optimize;
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "ocr_text" not in columns:
                connection.execute("ALTER TABLE messages ADD COLUMN ocr_text TEXT")
            research_columns = {row["name"] for row in connection.execute("PRAGMA table_info(research_reports)").fetchall()}
            if "research_type" not in research_columns:
                connection.execute("ALTER TABLE research_reports ADD COLUMN research_type TEXT NOT NULL DEFAULT 'ai_general'")
            if "idempotency_key" not in research_columns:
                connection.execute("ALTER TABLE research_reports ADD COLUMN idempotency_key TEXT")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_research_reports_idempotency ON research_reports(idempotency_key) WHERE idempotency_key IS NOT NULL")
            reminder_columns = {row["name"] for row in connection.execute("PRAGMA table_info(reminders)").fetchall()}
            if "recurrence" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'once'")
            if "range_start" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN range_start INTEGER")
            if "range_end" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN range_end INTEGER")
            if "event_at" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN event_at TEXT")

    def list_reminders(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM reminders ORDER BY done, due_at").fetchall()
        return [{**dict(row), "done": bool(row["done"])} for row in rows]

    def create_reminder(self, text: str, due_at: str, recurrence: str = "once", range_start: int | None = None, range_end: int | None = None, event_at: str | None = None) -> dict:
        item = {"id": str(uuid4()), "text": text.strip(), "due_at": due_at, "event_at": event_at, "recurrence": recurrence, "range_start": range_start, "range_end": range_end, "done": False, "created_at": _now()}
        with self._connect() as connection:
            connection.execute("INSERT INTO reminders (id,text,due_at,event_at,done,created_at,recurrence,range_start,range_end) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)", (item["id"], item["text"], due_at, event_at, item["created_at"], recurrence, range_start, range_end))
        return item

    def complete_reminder(self, reminder_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))

    def delete_reminder(self, reminder_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))

    def list_research_reports(self, research_type: str = "ai_general") -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, created_at, title, content, sources_json, research_type "
                "FROM research_reports WHERE research_type = ? ORDER BY created_at DESC",
                (research_type,),
            ).fetchall()
        return [self._research_dict(row) for row in rows]

    def create_research_report(self, content: str, sources: list[str], research_type: str = "ai_general", idempotency_key: str | None = None) -> dict:
        if idempotency_key:
            existing = self.get_research_report_by_idempotency_key(idempotency_key)
            if existing:
                return existing
        report_id = str(uuid4())
        timestamp = _now()
        title = "Mobilappar & trender" if research_type == "mobile_apps" else "AI-omvärldsbevakning"
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO research_reports "
                    "(id, created_at, title, content, sources_json, research_type, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (report_id, timestamp, title, content, json.dumps(sources), research_type, idempotency_key),
                )
        except sqlite3.IntegrityError:
            if idempotency_key:
                existing = self.get_research_report_by_idempotency_key(idempotency_key)
                if existing:
                    return existing
            raise
        return self._research_dict(
            {"id": report_id, "created_at": timestamp, "title": title, "content": content, "sources_json": json.dumps(sources), "research_type": research_type}
        )

    def get_research_report_by_idempotency_key(self, key: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, created_at, title, content, sources_json, research_type FROM research_reports WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return self._research_dict(row) if row else None

    def list_conversations(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, created_at, updated_at "
                "FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, title: str = "Ny chatt") -> dict:
        conversation_id = str(uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (conversation_id, title.strip(), timestamp, timestamp),
            )
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("Chatten finns inte.")
        return dict(row)

    def rename_conversation(self, conversation_id: str, title: str) -> dict:
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip(), timestamp, conversation_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("Chatten finns inte.")
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as connection:
            image_rows = connection.execute(
                "SELECT image_filename FROM messages "
                "WHERE conversation_id = ? AND image_filename IS NOT NULL",
                (conversation_id,),
            ).fetchall()
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError("Chatten finns inte.")
        for row in image_rows:
            self._attachment_path(row["image_filename"]).unlink(missing_ok=True)

    def messages(self, conversation_id: str) -> list[dict]:
        self.get_conversation(conversation_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, role, content, image_filename, ocr_text, created_at "
                "FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        return [self._message_dict(row) for row in rows]

    def model_messages(self, conversation_id: str) -> list[dict]:
        self.get_conversation(conversation_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content, image_filename, ocr_text FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        result = []
        for row in rows:
            content = row["content"]
            if row["ocr_text"]:
                content = (
                    f"{content}\n\n[Lokalt OCR-utdrag från bilden]\n"
                    f"{row['ocr_text']}"
                ).strip()
            item = {"role": row["role"], "content": content, "images": []}
            if row["image_filename"]:
                payload = self.attachment_path(row["image_filename"]).read_bytes()
                item["images"] = [base64.b64encode(payload).decode("ascii")]
            result.append(item)
        return result

    def add_exchange(
        self,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        image_filename: str | None,
        ocr_text: str | None = None,
    ) -> tuple[dict, dict, dict]:
        self.get_conversation(conversation_id)
        user_id = str(uuid4())
        assistant_id = str(uuid4())
        user_time = _now()
        assistant_time = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, image_filename, ocr_text, created_at) "
                "VALUES (?, ?, 'user', ?, ?, ?, ?)",
                (
                    user_id,
                    conversation_id,
                    user_content,
                    image_filename,
                    ocr_text,
                    user_time,
                ),
            )
            connection.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, image_filename, ocr_text, created_at) "
                "VALUES (?, ?, 'assistant', ?, NULL, NULL, ?)",
                (assistant_id, conversation_id, assistant_content, assistant_time),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (assistant_time, conversation_id),
            )
            current = connection.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if current and current["title"] == "Ny chatt":
                generated_title = user_content.strip() or "Skärmdump"
                generated_title = generated_title.replace("\n", " ")[:60]
                connection.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (generated_title, conversation_id),
                )
        messages = self.messages(conversation_id)
        return self.get_conversation(conversation_id), messages[-2], messages[-1]

    def save_image(self, image: ImageAttachment) -> tuple[str, str]:
        try:
            payload = base64.b64decode(image.data_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise StorageError("Bilden innehåller ogiltig base64-data.") from exc
        if len(payload) > 10 * 1024 * 1024:
            raise StorageError("Bilden är större än 10 MB.")
        signatures = {
            "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
            "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
            "image/webp": (b"RIFF", ".webp"),
        }
        signature, extension = signatures[image.mime_type]
        if not payload.startswith(signature):
            raise StorageError("Bildens innehåll stämmer inte med filtypen.")
        if image.mime_type == "image/webp" and payload[8:12] != b"WEBP":
            raise StorageError("Ogiltig WebP-bild.")
        filename = f"{uuid4()}{extension}"
        self._attachment_path(filename).write_bytes(payload)
        return filename, image.data_base64

    def attachment_path(self, filename: str) -> Path:
        path = self._attachment_path(filename)
        if not path.is_file():
            raise NotFoundError("Bilden finns inte.")
        return path

    def _attachment_path(self, filename: str) -> Path:
        if Path(filename).name != filename:
            raise StorageError("Ogiltigt bildnamn.")
        path = (self.attachments_dir / filename).resolve()
        if path.parent != self.attachments_dir:
            raise StorageError("Ogiltig bildsökväg.")
        return path

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        filename = result.pop("image_filename")
        result["image_url"] = f"/api/attachments/{filename}" if filename else None
        return result

    @staticmethod
    def _research_dict(row: sqlite3.Row | dict) -> dict:
        result = dict(row)
        result["sources"] = json.loads(result.pop("sources_json"))
        return result
