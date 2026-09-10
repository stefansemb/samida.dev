from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from winotify import Notification

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "samida.db"
STATE = ROOT / "data" / "reminder-notifications.json"

def main() -> None:
    if not DB.exists():
        return
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    now = datetime.now()
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT id,text,due_at,done,recurrence FROM reminders WHERE done=0").fetchall()
        for row in rows:
            try:
                due = datetime.fromisoformat(row["due_at"])
            except ValueError:
                continue
            if due > now:
                continue
            key = f"{row['id']}:{row['due_at']}"
            if state.get(key):
                continue
            toast = Notification(app_id="SAMIDA", title="SAMIDA-påminnelse", msg=row["text"])
            toast.show()
            state[key] = now.isoformat(timespec="seconds")
            if row["recurrence"] == "once":
                db.execute("UPDATE reminders SET done=1 WHERE id=?", (row["id"],))
        db.commit()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
