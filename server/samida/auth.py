import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, Response

from samida.dependencies import get_conversation_store
from samida.storage import ConversationStore

SESSION_COOKIE_NAME = "samida_session"
SESSION_TTL = timedelta(days=30)


@dataclass
class User:
    id: str
    email: str
    tier: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_session(store: ConversationStore, user_id: str) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + SESSION_TTL
    store.create_session(hash_token(raw_token), user_id, expires_at.isoformat())
    return raw_token, expires_at


def set_session_cookie(response: Response, raw_token: str, expires_at: datetime, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        expires=expires_at,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


async def get_current_user(
    request: Request,
    store: ConversationStore = Depends(get_conversation_store),
) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=401, detail="You are not logged in.")
    session = store.get_session_with_user(hash_token(raw_token))
    if session is None:
        raise HTTPException(status_code=401, detail="Your session is invalid or has expired.")
    store.touch_session(session["session_id"])
    return User(id=session["user_id"], email=session["email"], tier=session["tier"])
