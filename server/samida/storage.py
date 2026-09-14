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
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed')),
                    result_json TEXT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    browser_workspace INTEGER NOT NULL DEFAULT 0,
                    skill TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation
                    ON tool_calls(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'full',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS provider_credentials (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    provider_kind TEXT NOT NULL CHECK (provider_kind IN ('chat', 'image')),
                    provider_key TEXT NOT NULL,
                    api_key_encrypted TEXT NOT NULL,
                    base_url_override TEXT,
                    default_model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (user_id, provider_kind, provider_key)
                );
                CREATE INDEX IF NOT EXISTS idx_provider_credentials_user ON provider_credentials(user_id);
                CREATE TABLE IF NOT EXISTS model_catalog (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('chat', 'image')),
                    provider_key TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    supports_vision INTEGER NOT NULL DEFAULT 0,
                    supports_tools INTEGER NOT NULL DEFAULT 0,
                    requires_user_key INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (kind, provider_key, model_name)
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notes_owner_created ON notes(owner_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS oauth_connections (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    access_token_encrypted TEXT NOT NULL,
                    refresh_token_encrypted TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (owner_id, provider)
                );
                PRAGMA optimize;
                """
            )
            self._seed_model_catalog(connection)
            tool_call_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tool_calls)").fetchall()}
            if "browser_workspace" not in tool_call_columns:
                connection.execute("ALTER TABLE tool_calls ADD COLUMN browser_workspace INTEGER NOT NULL DEFAULT 0")
            if "skill" not in tool_call_columns:
                connection.execute("ALTER TABLE tool_calls ADD COLUMN skill TEXT NOT NULL DEFAULT ''")
            conversation_columns = {row["name"] for row in connection.execute("PRAGMA table_info(conversations)").fetchall()}
            if "owner_id" not in conversation_columns:
                connection.execute("ALTER TABLE conversations ADD COLUMN owner_id TEXT REFERENCES users(id)")
            reminder_owner_columns = {row["name"] for row in connection.execute("PRAGMA table_info(reminders)").fetchall()}
            if "owner_id" not in reminder_owner_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN owner_id TEXT REFERENCES users(id)")
            research_owner_columns = {row["name"] for row in connection.execute("PRAGMA table_info(research_reports)").fetchall()}
            if "owner_id" not in research_owner_columns:
                connection.execute("ALTER TABLE research_reports ADD COLUMN owner_id TEXT REFERENCES users(id)")
                connection.execute("DROP INDEX IF EXISTS idx_research_reports_idempotency")
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "ocr_text" not in columns:
                connection.execute("ALTER TABLE messages ADD COLUMN ocr_text TEXT")
            if "tool_call_id" not in columns:
                connection.execute("ALTER TABLE messages ADD COLUMN tool_call_id TEXT REFERENCES tool_calls(id)")
            research_columns = {row["name"] for row in connection.execute("PRAGMA table_info(research_reports)").fetchall()}
            if "research_type" not in research_columns:
                connection.execute("ALTER TABLE research_reports ADD COLUMN research_type TEXT NOT NULL DEFAULT 'ai_general'")
            if "idempotency_key" not in research_columns:
                connection.execute("ALTER TABLE research_reports ADD COLUMN idempotency_key TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_research_reports_owner_idempotency "
                "ON research_reports(owner_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            reminder_columns = {row["name"] for row in connection.execute("PRAGMA table_info(reminders)").fetchall()}
            if "recurrence" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'once'")
            if "range_start" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN range_start INTEGER")
            if "range_end" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN range_end INTEGER")
            if "event_at" not in reminder_columns:
                connection.execute("ALTER TABLE reminders ADD COLUMN event_at TEXT")

    @staticmethod
    def _seed_model_catalog(connection: sqlite3.Connection) -> None:
        # Ollama's own models are discovered live via the provider's model_names()
        # (whatever the operator has pulled), so only the API-key-gated chat
        # providers are seeded here. Adding a new model for one of these providers
        # later is a single INSERT — no code change required.
        seed_rows = [
            ("chat", "openai", "gpt-5.6-luna", "OpenAI · gpt-5.6-luna", 1, 1, 1, 0),
            ("chat", "openai", "gpt-5.6-terra", "OpenAI · gpt-5.6-terra", 1, 1, 1, 1),
            ("chat", "openai", "gpt-5.6-sol", "OpenAI · gpt-5.6-sol", 1, 1, 1, 2),
            ("chat", "anthropic", "claude-opus-5", "Claude · claude-opus-5", 1, 1, 1, 0),
            ("chat", "anthropic", "claude-sonnet-5", "Claude · claude-sonnet-5", 1, 1, 1, 1),
            ("chat", "anthropic", "claude-haiku-4-5", "Claude · claude-haiku-4-5", 1, 1, 1, 2),
        ]
        for kind, provider_key, model_name, display_name, vision, tools, requires_key, sort_order in seed_rows:
            connection.execute(
                "INSERT OR IGNORE INTO model_catalog "
                "(id, kind, provider_key, model_name, display_name, supports_vision, "
                "supports_tools, requires_user_key, sort_order, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (str(uuid4()), kind, provider_key, model_name, display_name, vision, tools, requires_key, sort_order),
            )

    def list_model_catalog(self, kind: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT provider_key, model_name, display_name, supports_vision, supports_tools, "
                "requires_user_key FROM model_catalog WHERE kind = ? AND enabled = 1 "
                "ORDER BY provider_key, sort_order",
                (kind,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_user(self, email: str, password_hash: str) -> dict:
        user_id = str(uuid4())
        timestamp = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, tier, is_active, created_at) "
                    "VALUES (?, ?, ?, 'full', 1, ?)",
                    (user_id, email, password_hash, timestamp),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageError("This email address is already in use.") from exc
        return self.get_user_by_id(user_id)

    def get_user_by_email(self, email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, password_hash, tier, is_active, created_at "
                "FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, password_hash, tier, is_active, created_at "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("The user does not exist.")
        return dict(row)

    def create_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, user_id, created_at, expires_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (token_hash, user_id, timestamp, expires_at, timestamp),
            )

    def get_session_with_user(self, token_hash: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT s.id AS session_id, s.expires_at, "
                "u.id AS user_id, u.email, u.tier, u.is_active "
                "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] < _now() or not row["is_active"]:
                connection.execute("DELETE FROM sessions WHERE id = ?", (token_hash,))
                return None
        return dict(row)

    def touch_session(self, token_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (_now(), token_hash)
            )

    def delete_session(self, token_hash: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (token_hash,))

    def upsert_provider_credential(
        self,
        user_id: str,
        provider_kind: str,
        provider_key: str,
        api_key_encrypted: str,
        base_url_override: str | None = None,
        default_model: str | None = None,
    ) -> dict:
        timestamp = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM provider_credentials WHERE user_id = ? AND provider_kind = ? AND provider_key = ?",
                (user_id, provider_kind, provider_key),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE provider_credentials SET api_key_encrypted = ?, base_url_override = ?, "
                    "default_model = ?, updated_at = ? WHERE id = ?",
                    (api_key_encrypted, base_url_override, default_model, timestamp, existing["id"]),
                )
                credential_id = existing["id"]
            else:
                credential_id = str(uuid4())
                connection.execute(
                    "INSERT INTO provider_credentials "
                    "(id, user_id, provider_kind, provider_key, api_key_encrypted, base_url_override, "
                    "default_model, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (credential_id, user_id, provider_kind, provider_key, api_key_encrypted, base_url_override, default_model, timestamp, timestamp),
                )
        return self._get_provider_credential_by_id(credential_id)

    def _get_provider_credential_by_id(self, credential_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM provider_credentials WHERE id = ?", (credential_id,)
            ).fetchone()
        return dict(row)

    def get_provider_credential(self, user_id: str, provider_kind: str, provider_key: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM provider_credentials WHERE user_id = ? AND provider_kind = ? AND provider_key = ?",
                (user_id, provider_kind, provider_key),
            ).fetchone()
        return dict(row) if row else None

    def list_provider_credentials(self, user_id: str, provider_kind: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT provider_key, base_url_override, default_model, updated_at "
                "FROM provider_credentials WHERE user_id = ? AND provider_kind = ?",
                (user_id, provider_kind),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_provider_credential(self, user_id: str, provider_kind: str, provider_key: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM provider_credentials WHERE user_id = ? AND provider_kind = ? AND provider_key = ?",
                (user_id, provider_kind, provider_key),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("Ingen sparad nyckel hittades.")

    def list_reminders(self, owner_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reminders WHERE owner_id = ? ORDER BY done, due_at", (owner_id,)
            ).fetchall()
        return [{**dict(row), "done": bool(row["done"])} for row in rows]

    def create_reminder(self, owner_id: str, text: str, due_at: str, recurrence: str = "once", range_start: int | None = None, range_end: int | None = None, event_at: str | None = None) -> dict:
        item = {"id": str(uuid4()), "text": text.strip(), "due_at": due_at, "event_at": event_at, "recurrence": recurrence, "range_start": range_start, "range_end": range_end, "done": False, "created_at": _now()}
        with self._connect() as connection:
            connection.execute("INSERT INTO reminders (id,text,due_at,event_at,done,created_at,recurrence,range_start,range_end,owner_id) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)", (item["id"], item["text"], due_at, event_at, item["created_at"], recurrence, range_start, range_end, owner_id))
        return item

    def complete_reminder(self, reminder_id: str, owner_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute("UPDATE reminders SET done=1 WHERE id=? AND owner_id=?", (reminder_id, owner_id))
        if cursor.rowcount == 0:
            raise NotFoundError("The reminder does not exist.")

    def delete_reminder(self, reminder_id: str, owner_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM reminders WHERE id=? AND owner_id=?", (reminder_id, owner_id))
        if cursor.rowcount == 0:
            raise NotFoundError("The reminder does not exist.")

    def save_note(self, owner_id: str, content: str) -> dict:
        item = {"id": str(uuid4()), "content": content.strip(), "created_at": _now()}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO notes (id, owner_id, content, created_at) VALUES (?, ?, ?, ?)",
                (item["id"], owner_id, item["content"], item["created_at"]),
            )
        return item

    def list_notes(self, owner_id: str, query: str | None = None, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            if query:
                rows = connection.execute(
                    "SELECT id, content, created_at FROM notes WHERE owner_id = ? "
                    "AND content LIKE ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (owner_id, f"%{query}%", limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, content, created_at FROM notes WHERE owner_id = ? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (owner_id, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def save_oauth_connection(
        self, owner_id: str, provider: str, access_token_encrypted: str, refresh_token_encrypted: str, expires_at: str, scope: str
    ) -> None:
        timestamp = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM oauth_connections WHERE owner_id = ? AND provider = ?", (owner_id, provider)
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE oauth_connections SET access_token_encrypted = ?, refresh_token_encrypted = ?, "
                    "expires_at = ?, scope = ?, updated_at = ? WHERE id = ?",
                    (access_token_encrypted, refresh_token_encrypted, expires_at, scope, timestamp, existing["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO oauth_connections (id, owner_id, provider, access_token_encrypted, "
                    "refresh_token_encrypted, expires_at, scope, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), owner_id, provider, access_token_encrypted, refresh_token_encrypted, expires_at, scope, timestamp, timestamp),
                )

    def update_oauth_access_token(self, owner_id: str, provider: str, access_token_encrypted: str, expires_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE oauth_connections SET access_token_encrypted = ?, expires_at = ?, updated_at = ? "
                "WHERE owner_id = ? AND provider = ?",
                (access_token_encrypted, expires_at, _now(), owner_id, provider),
            )

    def get_oauth_connection(self, owner_id: str, provider: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_connections WHERE owner_id = ? AND provider = ?", (owner_id, provider)
            ).fetchone()
        return dict(row) if row else None

    def delete_oauth_connection(self, owner_id: str, provider: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_connections WHERE owner_id = ? AND provider = ?", (owner_id, provider))

    def list_research_reports(self, owner_id: str, research_type: str = "ai_general") -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, created_at, title, content, sources_json, research_type "
                "FROM research_reports WHERE owner_id = ? AND research_type = ? ORDER BY created_at DESC",
                (owner_id, research_type),
            ).fetchall()
        return [self._research_dict(row) for row in rows]

    def create_research_report(self, owner_id: str, content: str, sources: list[str], research_type: str = "ai_general", idempotency_key: str | None = None) -> dict:
        if idempotency_key:
            existing = self.get_research_report_by_idempotency_key(owner_id, idempotency_key)
            if existing:
                return existing
        report_id = str(uuid4())
        timestamp = _now()
        title = "Mobile apps & trends" if research_type == "mobile_apps" else "AI industry watch"
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO research_reports "
                    "(id, created_at, title, content, sources_json, research_type, idempotency_key, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (report_id, timestamp, title, content, json.dumps(sources), research_type, idempotency_key, owner_id),
                )
        except sqlite3.IntegrityError:
            if idempotency_key:
                existing = self.get_research_report_by_idempotency_key(owner_id, idempotency_key)
                if existing:
                    return existing
            raise
        return self._research_dict(
            {"id": report_id, "created_at": timestamp, "title": title, "content": content, "sources_json": json.dumps(sources), "research_type": research_type}
        )

    def get_research_report_by_idempotency_key(self, owner_id: str, key: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, created_at, title, content, sources_json, research_type "
                "FROM research_reports WHERE owner_id = ? AND idempotency_key = ?",
                (owner_id, key),
            ).fetchone()
        return self._research_dict(row) if row else None

    def list_conversations(self, owner_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, created_at, updated_at "
                "FROM conversations WHERE owner_id = ? ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, owner_id: str, title: str = "New chat") -> dict:
        conversation_id = str(uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, owner_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, title.strip(), timestamp, timestamp, owner_id),
            )
        return self.get_conversation(conversation_id, owner_id)

    def get_conversation(self, conversation_id: str, owner_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE id = ? AND owner_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("The chat does not exist.")
        return dict(row)

    def rename_conversation(self, conversation_id: str, owner_id: str, title: str) -> dict:
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                (title.strip(), timestamp, conversation_id, owner_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("The chat does not exist.")
        return self.get_conversation(conversation_id, owner_id)

    def delete_conversation(self, conversation_id: str, owner_id: str) -> None:
        with self._connect() as connection:
            image_rows = connection.execute(
                "SELECT image_filename FROM messages "
                "WHERE conversation_id = ? AND image_filename IS NOT NULL",
                (conversation_id,),
            ).fetchall()
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ? AND owner_id = ?", (conversation_id, owner_id)
            )
        if cursor.rowcount == 0:
            raise NotFoundError("The chat does not exist.")
        for row in image_rows:
            self._attachment_path(row["image_filename"]).unlink(missing_ok=True)

    def messages(self, conversation_id: str, owner_id: str) -> list[dict]:
        self.get_conversation(conversation_id, owner_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT m.id, m.role, m.content, m.image_filename, m.ocr_text, m.created_at, "
                "tc.id AS tc_id, tc.tool_name AS tc_tool_name, tc.arguments_json AS tc_arguments_json, "
                "tc.risk_level AS tc_risk_level, tc.status AS tc_status, tc.created_at AS tc_created_at "
                "FROM messages m LEFT JOIN tool_calls tc ON tc.id = m.tool_call_id "
                "WHERE m.conversation_id = ? ORDER BY m.created_at",
                (conversation_id,),
            ).fetchall()
        return [self._message_dict(row) for row in rows]

    def model_messages(self, conversation_id: str, owner_id: str) -> list[dict]:
        self.get_conversation(conversation_id, owner_id)
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
                    f"{content}\n\n[Local OCR excerpt from the image]\n"
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
        owner_id: str,
        user_content: str,
        assistant_content: str,
        image_filename: str | None,
        ocr_text: str | None = None,
        assistant_tool_call_id: str | None = None,
        assistant_image_filename: str | None = None,
    ) -> tuple[dict, dict, dict]:
        self.get_conversation(conversation_id, owner_id)
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
                "(id, conversation_id, role, content, image_filename, ocr_text, created_at, tool_call_id) "
                "VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?)",
                (assistant_id, conversation_id, assistant_content, assistant_image_filename, assistant_time, assistant_tool_call_id),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (assistant_time, conversation_id),
            )
            current = connection.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if current and current["title"] == "New chat":
                generated_title = user_content.strip() or "Screenshot"
                generated_title = generated_title.replace("\n", " ")[:60]
                connection.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (generated_title, conversation_id),
                )
        messages = self.messages(conversation_id, owner_id)
        return self.get_conversation(conversation_id, owner_id), messages[-2], messages[-1]

    def append_assistant_message(
        self,
        conversation_id: str,
        owner_id: str,
        content: str,
        tool_call_id: str | None = None,
        image_filename: str | None = None,
    ) -> tuple[dict, dict]:
        self.get_conversation(conversation_id, owner_id)
        message_id = str(uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, image_filename, ocr_text, created_at, tool_call_id) "
                "VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?)",
                (message_id, conversation_id, content, image_filename, timestamp, tool_call_id),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (timestamp, conversation_id),
            )
        messages = self.messages(conversation_id, owner_id)
        return self.get_conversation(conversation_id, owner_id), messages[-1]

    def create_pending_tool_call(
        self,
        conversation_id: str,
        owner_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        risk_level: str,
        provider: str,
        model: str,
        profile: str,
        working_directory: str,
        browser_workspace: bool = False,
        skill: str = "",
    ) -> dict:
        self.get_conversation(conversation_id, owner_id)
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tool_calls "
                "(id, conversation_id, tool_name, arguments_json, risk_level, status, "
                "provider, model, profile, working_directory, browser_workspace, skill, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
                (
                    tool_call_id,
                    conversation_id,
                    tool_name,
                    json.dumps(arguments),
                    risk_level,
                    provider,
                    model,
                    profile,
                    working_directory,
                    int(browser_workspace),
                    skill,
                    timestamp,
                ),
            )
        return self.get_tool_call(tool_call_id, owner_id)

    def get_tool_call(self, tool_call_id: str, owner_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT tc.* FROM tool_calls tc "
                "JOIN conversations c ON c.id = tc.conversation_id "
                "WHERE tc.id = ? AND c.owner_id = ?",
                (tool_call_id, owner_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("The tool call does not exist.")
        return self._tool_call_dict(row)

    def resolve_tool_call(self, tool_call_id: str, owner_id: str, status: str, result: dict | None = None) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tool_calls SET status = ?, result_json = ?, resolved_at = ? "
                "WHERE id = ? AND status = 'pending' "
                "AND conversation_id IN (SELECT id FROM conversations WHERE owner_id = ?)",
                (status, json.dumps(result) if result is not None else None, _now(), tool_call_id, owner_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("The tool call does not exist or has already been resolved.")
        return self.get_tool_call(tool_call_id, owner_id)

    @staticmethod
    def _tool_call_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["arguments"] = json.loads(result.pop("arguments_json"))
        raw_result = result.pop("result_json")
        result["result"] = json.loads(raw_result) if raw_result else None
        result["browser_workspace"] = bool(result["browser_workspace"])
        return result

    def save_image(self, image: ImageAttachment) -> tuple[str, str]:
        try:
            payload = base64.b64decode(image.data_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise StorageError("The image contains invalid base64 data.") from exc
        if len(payload) > 10 * 1024 * 1024:
            raise StorageError("The image is larger than 10 MB.")
        signatures = {
            "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
            "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
            "image/webp": (b"RIFF", ".webp"),
        }
        signature, extension = signatures[image.mime_type]
        if not payload.startswith(signature):
            raise StorageError("The image content does not match its file type.")
        if image.mime_type == "image/webp" and payload[8:12] != b"WEBP":
            raise StorageError("Invalid WebP image.")
        filename = f"{uuid4()}{extension}"
        self._attachment_path(filename).write_bytes(payload)
        return filename, image.data_base64

    def save_generated_image(self, image_bytes: bytes, mime_type: str) -> str:
        extensions = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
        }
        extension = extensions.get(mime_type.lower(), ".png")
        filename = f"{uuid4()}{extension}"
        self._attachment_path(filename).write_bytes(image_bytes)
        return filename

    def attachment_owner_id(self, filename: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT c.owner_id FROM messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.image_filename = ?",
                (filename,),
            ).fetchone()
        return row["owner_id"] if row else None

    def attachment_path(self, filename: str) -> Path:
        path = self._attachment_path(filename)
        if not path.is_file():
            raise NotFoundError("The image does not exist.")
        return path

    def _attachment_path(self, filename: str) -> Path:
        if Path(filename).name != filename:
            raise StorageError("Invalid image filename.")
        path = (self.attachments_dir / filename).resolve()
        if path.parent != self.attachments_dir:
            raise StorageError("Invalid image path.")
        return path

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict:
        raw = dict(row)
        filename = raw.pop("image_filename")
        tc_id = raw.pop("tc_id", None)
        tool_call = None
        if tc_id:
            tool_call = {
                "id": tc_id,
                "tool_name": raw.pop("tc_tool_name"),
                "arguments": json.loads(raw.pop("tc_arguments_json")),
                "risk_level": raw.pop("tc_risk_level"),
                "status": raw.pop("tc_status"),
                "created_at": raw.pop("tc_created_at"),
            }
        else:
            for key in ("tc_tool_name", "tc_arguments_json", "tc_risk_level", "tc_status", "tc_created_at"):
                raw.pop(key, None)
        return {
            **raw,
            "image_url": f"/api/attachments/{filename}" if filename else None,
            "tool_call": tool_call,
        }

    @staticmethod
    def _research_dict(row: sqlite3.Row | dict) -> dict:
        result = dict(row)
        result["sources"] = json.loads(result.pop("sources_json"))
        return result
