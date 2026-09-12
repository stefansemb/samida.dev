from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from samida.config import Settings
from samida.crypto import decrypt_secret, encrypt_secret
from samida.storage import ConversationStore

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

# Read-only to start - see [[project_plugins_tools_byok]] for the BYOK
# philosophy this follows; this is the one exception since Google OAuth is
# inherently a shared app-level credential, not a per-user API key.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

PROVIDER = "google"


class GoogleOAuthError(RuntimeError):
    pass


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GoogleOAuthError("Google rejected the authorization code.") from exc
    return response.json()


async def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GoogleOAuthError("Could not refresh the Google connection.") from exc
    return response.json()


class GoogleIntegration:
    """Per-request helper that keeps a user's Google access token valid,
    refreshing it against the stored refresh_token when it has expired."""

    def __init__(self, store: ConversationStore, settings: Settings, owner_id: str) -> None:
        self._store = store
        self._settings = settings
        self._owner_id = owner_id

    def is_connected(self) -> bool:
        return self._store.get_oauth_connection(self._owner_id, PROVIDER) is not None

    async def get_valid_access_token(self) -> str | None:
        connection = self._store.get_oauth_connection(self._owner_id, PROVIDER)
        if connection is None:
            return None
        expires_at = datetime.fromisoformat(connection["expires_at"])
        if expires_at > datetime.now(UTC) + timedelta(seconds=60):
            return decrypt_secret(connection["access_token_encrypted"], self._settings)

        if not (self._settings.google_client_id and self._settings.google_client_secret):
            raise GoogleOAuthError("Google integration is not configured on this server.")
        refresh_token = decrypt_secret(connection["refresh_token_encrypted"], self._settings)
        payload = await _refresh_access_token(
            self._settings.google_client_id, self._settings.google_client_secret, refresh_token
        )
        new_expires_at = datetime.now(UTC) + timedelta(seconds=payload["expires_in"])
        access_token = payload["access_token"]
        self._store.update_oauth_access_token(
            self._owner_id, PROVIDER, encrypt_secret(access_token, self._settings), new_expires_at.isoformat()
        )
        return access_token

    def disconnect(self) -> None:
        self._store.delete_oauth_connection(self._owner_id, PROVIDER)


@dataclass(frozen=True)
class CalendarEvent:
    summary: str
    start: str
    end: str
    location: str | None


class GoogleCalendarError(RuntimeError):
    pass


async def list_upcoming_events(access_token: str, max_results: int = 10) -> list[CalendarEvent]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                CALENDAR_EVENTS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "timeMin": datetime.now(UTC).isoformat(),
                    "maxResults": max_results,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GoogleCalendarError("Could not read Google Calendar.") from exc

    items = response.json().get("items", [])
    return [
        CalendarEvent(
            summary=item.get("summary", "(No title)"),
            start=item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", ""),
            end=item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", ""),
            location=item.get("location"),
        )
        for item in items
    ]


@dataclass(frozen=True)
class EmailSummary:
    subject: str
    sender: str
    date: str
    snippet: str


class GmailError(RuntimeError):
    pass


async def list_recent_emails(access_token: str, query: str = "", max_results: int = 5) -> list[EmailSummary]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            list_response = await client.get(
                GMAIL_MESSAGES_URL,
                headers=headers,
                params={"maxResults": max_results, **({"q": query} if query else {})},
            )
            list_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GmailError("Could not read Gmail.") from exc

        message_ids = [item["id"] for item in list_response.json().get("messages", [])]
        summaries: list[EmailSummary] = []
        for message_id in message_ids:
            try:
                detail_response = await client.get(
                    f"{GMAIL_MESSAGES_URL}/{message_id}",
                    headers=headers,
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                )
                detail_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise GmailError("Could not read a Gmail message.") from exc
            payload = detail_response.json()
            header_values = {h["name"]: h["value"] for h in payload.get("payload", {}).get("headers", [])}
            summaries.append(
                EmailSummary(
                    subject=header_values.get("Subject", "(No subject)"),
                    sender=header_values.get("From", ""),
                    date=header_values.get("Date", ""),
                    snippet=payload.get("snippet", ""),
                )
            )
    return summaries
