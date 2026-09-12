"""One-off migration: create the first real account and assign it ownership
of all pre-existing (pre-multi-user) conversations, reminders and research
reports, whose owner_id is currently NULL.

Run once, manually, after deploying the Phase 2 auth/ownership release and
before removing anonymous access:

    SAMIDA_BOOTSTRAP_EMAIL=you@example.com SAMIDA_BOOTSTRAP_PASSWORD=... \
        python server/scripts/bootstrap_owner.py

If the env vars are omitted you will be prompted interactively. Safe to
re-run: it no-ops once the account exists and no NULL-owner rows remain.
"""

import getpass
import os
import sqlite3

from samida import auth
from samida.config import get_settings
from samida.storage import ConversationStore


def main() -> None:
    settings = get_settings()
    store = ConversationStore(settings.resolved_database_path(), settings.resolved_attachments_dir())

    email = (os.environ.get("SAMIDA_BOOTSTRAP_EMAIL") or input("Email: ")).strip().lower()
    existing = store.get_user_by_email(email)
    if existing:
        user_id = existing["id"]
        print(f"Account {email} already exists, reusing it.")
    else:
        password = os.environ.get("SAMIDA_BOOTSTRAP_PASSWORD") or getpass.getpass("Password: ")
        user = store.create_user(email, auth.hash_password(password))
        user_id = user["id"]
        print(f"Created account {email}.")

    with sqlite3.connect(settings.resolved_database_path()) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for table in ("conversations", "reminders", "research_reports"):
            cursor = connection.execute(
                f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL", (user_id,)
            )
            print(f"{table}: {cursor.rowcount} row(s) assigned to {email}.")


if __name__ == "__main__":
    main()
