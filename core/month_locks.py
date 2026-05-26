"""נעילת חודש — מנגנון לסגירת חודש כדי למנוע שינויים בנתונים.

טבלה: month_locks
שדות: project_id, month, locked_by, locked_at, notes

נעילה היא אינדיקטיבית: המערכת לא חוסמת פיזית עריכה, רק מציגה אזהרה
ודורשת אישור מנהל לפעולות שמשנות חודש סגור.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "project_control.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS month_locks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    month       TEXT NOT NULL,
    locked_by   TEXT DEFAULT '',
    locked_at   TEXT,
    notes       TEXT DEFAULT '',
    UNIQUE(project_id, month)
);
CREATE INDEX IF NOT EXISTS idx_locks_project ON month_locks(project_id);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def lock_month(project_id: str, month: str, locked_by: str = "",
                 notes: str = "") -> tuple[bool, str]:
    """נועל חודש. מחזיר (success, message)."""
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO month_locks
                   (project_id, month, locked_by, locked_at, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, month, locked_by, now, notes),
            )
        # audit
        try:
            from core import db
            db.log_event("month_locked", {
                "project_id": project_id, "month": month,
                "locked_by": locked_by, "notes": notes,
            })
        except Exception:
            pass
        return True, f"חודש {month} נעול"
    except Exception as e:
        logger.exception("Failed to lock month: %s", e)
        return False, f"שגיאה בנעילה: {e}"


def unlock_month(project_id: str, month: str,
                   reason: str = "") -> tuple[bool, str]:
    """מבטל נעילה (פותח חודש מחדש). דורש סיבה לטובת audit."""
    init_db()
    try:
        with _conn() as c:
            cur = c.execute(
                "DELETE FROM month_locks WHERE project_id = ? AND month = ?",
                (project_id, month),
            )
            n = cur.rowcount
        try:
            from core import db
            db.log_event("month_unlocked", {
                "project_id": project_id, "month": month,
                "reason": reason,
            })
        except Exception:
            pass
        return (n > 0, f"חודש {month} נפתח" if n > 0
                else f"חודש {month} לא היה נעול")
    except Exception as e:
        return False, f"שגיאה: {e}"


def is_locked(project_id: str, month: str) -> bool:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "SELECT 1 FROM month_locks WHERE project_id = ? AND month = ?",
            (project_id, month),
        )
        return cur.fetchone() is not None


def list_locks(project_id: str) -> pd.DataFrame:
    """מחזיר DataFrame של חודשים נעולים בפרויקט."""
    init_db()
    with _conn() as c:
        return pd.read_sql_query(
            "SELECT * FROM month_locks WHERE project_id = ? "
            "ORDER BY month DESC",
            c, params=[project_id],
        )
