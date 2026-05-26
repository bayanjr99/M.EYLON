"""משימות פרויקט — SQLite layer.

טבלה: project_tasks
שדות:
    id              INTEGER PRIMARY KEY
    project_id      TEXT NOT NULL
    title           TEXT NOT NULL
    description     TEXT
    assignee        TEXT
    due_date        TEXT (YYYY-MM-DD)
    status          TEXT (open / in_progress / done / cancelled)
    priority        TEXT (high / medium / low)
    related_issue_id INTEGER (FK לוגי ל-data_quality_issues, אופציונלי)
    related_alert   TEXT (כותרת התראה מקורית, אופציונלי)
    notes           TEXT
    created_at      TEXT
    updated_at      TEXT
    closed_at       TEXT

המודול עצמאי — לא משנה את control_db.py.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "project_control.sqlite"


VALID_STATUSES = ("open", "in_progress", "done", "cancelled")
STATUS_HE = {
    "open":         "פתוח",
    "in_progress":  "בטיפול",
    "done":         "נסגר",
    "cancelled":    "בוטל",
}

VALID_PRIORITIES = ("high", "medium", "low")
PRIORITY_HE = {"high": "גבוה", "medium": "בינוני", "low": "נמוך"}


SCHEMA = """
CREATE TABLE IF NOT EXISTS project_tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT DEFAULT '',
    assignee            TEXT DEFAULT '',
    due_date            TEXT DEFAULT '',
    status              TEXT DEFAULT 'open',
    priority            TEXT DEFAULT 'medium',
    related_issue_id    INTEGER DEFAULT NULL,
    related_alert       TEXT DEFAULT '',
    notes               TEXT DEFAULT '',
    created_at          TEXT,
    updated_at          TEXT,
    closed_at           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON project_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON project_tasks(status);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """יוצר את הטבלה אם אינה קיימת. בטוח לקריאות חוזרות."""
    with _conn() as c:
        c.executescript(SCHEMA)


def create_task(project_id: str, title: str, *,
                description: str = "", assignee: str = "",
                due_date: str = "", priority: str = "medium",
                related_issue_id: int | None = None,
                related_alert: str = "", notes: str = "") -> int:
    """יוצר משימה חדשה. מחזיר id."""
    init_db()
    if not title.strip():
        raise ValueError("title חובה")
    if priority not in VALID_PRIORITIES:
        priority = "medium"
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO project_tasks
               (project_id, title, description, assignee, due_date,
                status, priority, related_issue_id, related_alert,
                notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)""",
            (project_id, title.strip(), description.strip(),
             assignee.strip(), due_date.strip(), priority,
             related_issue_id, related_alert.strip(),
             notes.strip(), now, now),
        )
        return int(cur.lastrowid)


def update_task_status(task_id: int, status: str,
                        notes: str | None = None) -> bool:
    """משנה סטטוס של משימה. אם status='done' → גם רושם closed_at."""
    if status not in VALID_STATUSES:
        return False
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    fields = ["status = ?", "updated_at = ?"]
    values: list = [status, now]
    if status in ("done", "cancelled"):
        fields.append("closed_at = ?")
        values.append(now)
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes.strip())
    values.append(task_id)
    with _conn() as c:
        cur = c.execute(
            f"UPDATE project_tasks SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        return cur.rowcount > 0


def update_task(task_id: int, **fields) -> bool:
    """עדכון שדות חופשי. שדות מותרים בלבד."""
    allowed = {"title", "description", "assignee", "due_date",
               "priority", "notes"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return False
    init_db()
    safe["updated_at"] = datetime.now().isoformat(timespec="seconds")
    sets = ", ".join(f"{k} = ?" for k in safe)
    with _conn() as c:
        cur = c.execute(
            f"UPDATE project_tasks SET {sets} WHERE id = ?",
            list(safe.values()) + [task_id],
        )
        return cur.rowcount > 0


def delete_task(task_id: int) -> bool:
    init_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM project_tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0


def list_tasks(project_id: str, status: str = "all") -> pd.DataFrame:
    """מחזיר DataFrame של משימות לפרויקט.

    Args:
        project_id: מזהה הפרויקט.
        status: "all" / סטטוס ספציפי / "open_active" (open+in_progress).
    """
    init_db()
    q = "SELECT * FROM project_tasks WHERE project_id = ?"
    params: list = [project_id]
    if status == "open_active":
        q += " AND status IN ('open', 'in_progress')"
    elif status in VALID_STATUSES:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 " \
         "WHEN 'done' THEN 2 WHEN 'cancelled' THEN 3 ELSE 9 END, " \
         "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 9 END, " \
         "due_date NULLS LAST, id DESC"
    with _conn() as c:
        return pd.read_sql_query(q, c, params=params)


def count_tasks(project_id: str) -> dict[str, int]:
    """מחזיר ספירה לפי סטטוס לפרויקט."""
    init_db()
    with _conn() as c:
        df = pd.read_sql_query(
            "SELECT status, COUNT(*) AS n FROM project_tasks "
            "WHERE project_id = ? GROUP BY status",
            c, params=(project_id,),
        )
    return {row["status"]: int(row["n"]) for _, row in df.iterrows()}
