"""תקציב פרויקט - מטא-נתונים + תקציב לפי קטגוריה.

מבנה:
    project_metadata - שורה אחת לפרויקט עם פרטי החוזה והניהול
    project_budget   - שורה לכל (project_id, category) עם תקציב

חישוב ביצוע (actual) נעשה ב-aggregator לפי master.parquet — לא נשמר ב-DB.
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
CREATE TABLE IF NOT EXISTS project_metadata (
    project_id      TEXT PRIMARY KEY,
    client_name     TEXT,
    location        TEXT,
    start_date      TEXT,
    expected_end    TEXT,
    project_manager TEXT,
    contract_type   TEXT,   -- pausali / per_quantity / per_hour / other
    contract_amount REAL,
    contract_notes  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_budget (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    category    TEXT NOT NULL,
    budget      REAL NOT NULL DEFAULT 0,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(project_id, category)
);

CREATE INDEX IF NOT EXISTS idx_budget_project ON project_budget(project_id);
"""


# קטגוריות תקציב מקובלות (תואמות לקטגוריות שלנו)
DEFAULT_BUDGET_CATEGORIES = [
    "הכנסות",
    "סולר וצמ\"ה",
    "שכר עבודה",
    "קבלני משנה",
    "פינוי פסולת",
    "תשתיות",
    "אחזקת כלים",
    "רכבים",
    "אתר ותפעול",
    "ניהול ופיקוח",
    "הובלה",
    "ביטוחים",
    "משרד וכלכלה",
    "אגרות ורשויות",
    "הוצאות חריגות",
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """יוצר את הטבלאות (idempotent)."""
    with _connect() as conn:
        conn.executescript(SCHEMA)


# ── Metadata ──────────────────────────────────────────────────
def get_metadata(project_id: str) -> dict | None:
    """מחזיר dict עם מטא-נתוני הפרויקט, או None."""
    init()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM project_metadata WHERE project_id = ?", [project_id]
        ).fetchone()
    return dict(row) if row else None


def save_metadata(project_id: str, **fields) -> None:
    """upsert של פרטי הפרויקט."""
    init()
    now = datetime.now().isoformat(timespec="seconds")
    existing = get_metadata(project_id)
    if existing:
        # Update
        allowed = {"client_name", "location", "start_date", "expected_end",
                   "project_manager", "contract_type", "contract_amount",
                   "contract_notes"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
        params = list(fields.values()) + [now, project_id]
        with _connect() as conn:
            conn.execute(
                f"UPDATE project_metadata SET {set_clause} WHERE project_id = ?",
                params,
            )
    else:
        # Insert
        cols = ["project_id", "client_name", "location", "start_date", "expected_end",
                "project_manager", "contract_type", "contract_amount", "contract_notes",
                "created_at", "updated_at"]
        with _connect() as conn:
            conn.execute(
                f"INSERT INTO project_metadata ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})",
                [
                    project_id,
                    fields.get("client_name"),
                    fields.get("location"),
                    fields.get("start_date"),
                    fields.get("expected_end"),
                    fields.get("project_manager"),
                    fields.get("contract_type"),
                    fields.get("contract_amount"),
                    fields.get("contract_notes"),
                    now, now,
                ],
            )


# ── Budget ────────────────────────────────────────────────────
def get_budget(project_id: str) -> pd.DataFrame:
    """תקציב לפי קטגוריה. אם אין - מחזיר DataFrame ריק."""
    init()
    with _connect() as conn:
        return pd.read_sql(
            "SELECT category, budget, notes FROM project_budget WHERE project_id = ? ORDER BY category",
            conn, params=[project_id],
        )


def save_budget_row(project_id: str, category: str, budget: float,
                    notes: str = "") -> None:
    """upsert של תקציב לקטגוריה."""
    init()
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM project_budget WHERE project_id = ? AND category = ?",
            [project_id, category],
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE project_budget SET budget = ?, notes = ?, updated_at = ? WHERE id = ?",
                [budget, notes, now, existing["id"]],
            )
        else:
            conn.execute(
                """INSERT INTO project_budget
                   (project_id, category, budget, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [project_id, category, budget, notes, now, now],
            )


def save_budget_bulk(project_id: str, df: pd.DataFrame) -> int:
    """שומר DataFrame של תקציב (category, budget, notes). מחזיר מספר השורות."""
    if df.empty or "category" not in df.columns or "budget" not in df.columns:
        return 0
    saved = 0
    for _, r in df.iterrows():
        cat = str(r.get("category", "") or "").strip()
        if not cat:
            continue
        try:
            b = float(r.get("budget", 0) or 0)
        except (TypeError, ValueError):
            b = 0.0
        notes = str(r.get("notes", "") or "")
        save_budget_row(project_id, cat, b, notes)
        saved += 1
    return saved


def delete_budget(project_id: str, category: str) -> bool:
    init()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM project_budget WHERE project_id = ? AND category = ?",
            [project_id, category],
        )
        return cur.rowcount > 0


def compare_budget_vs_actual(project_id: str,
                              actuals_by_category: dict[str, float],
                              revenue_actual: float = 0.0) -> pd.DataFrame:
    """משווה תקציב vs ביצוע לכל קטגוריה.

    Args:
        actuals_by_category: dict של category → סה"כ הוצאה בפועל.
        revenue_actual: סה"כ הכנסה בפועל (לקטגוריית "הכנסות").

    Returns DataFrame עם: category, budget, actual, variance, util_pct, status.
    """
    budget_df = get_budget(project_id)
    if budget_df.empty:
        # מחזיר רק שורות actual (ללא תקציב)
        rows = [{"category": cat, "budget": 0, "actual": amt,
                 "variance": -amt, "util_pct": None, "status": "אין תקציב"}
                for cat, amt in actuals_by_category.items()]
        if revenue_actual:
            rows.insert(0, {"category": "הכנסות", "budget": 0,
                            "actual": revenue_actual, "variance": revenue_actual,
                            "util_pct": None, "status": "אין תקציב"})
        return pd.DataFrame(rows)

    all_cats = set(budget_df["category"].tolist()) | set(actuals_by_category.keys())
    if revenue_actual or "הכנסות" in budget_df["category"].values:
        all_cats.add("הכנסות")

    rows = []
    budget_dict = dict(zip(budget_df["category"], budget_df["budget"]))
    for cat in sorted(all_cats):
        b = float(budget_dict.get(cat, 0))
        if cat == "הכנסות":
            a = revenue_actual
        else:
            a = float(actuals_by_category.get(cat, 0))
        if cat == "הכנסות":
            # הכנסות: actual - budget. חיובי = עברנו את היעד
            variance = a - b
            util = (a / b * 100) if b > 0 else None
            if b == 0:
                status = "אין תקציב"
            elif a >= b:
                status = "✓ עומדים ביעד"
            elif a >= b * 0.9:
                status = "⚠ קרוב ליעד"
            else:
                status = "✗ פיגור משמעותי"
        else:
            # הוצאות: budget - actual. חיובי = נותר תקציב
            variance = b - a
            util = (a / b * 100) if b > 0 else None
            if b == 0:
                status = "אין תקציב"
            elif a > b:
                status = "✗ חריגה"
            elif a > b * 0.9:
                status = "⚠ קרוב לתקרה"
            else:
                status = "✓ בתוך התקציב"
        rows.append({
            "category": cat,
            "budget": round(b, 0),
            "actual": round(a, 0),
            "variance": round(variance, 0),
            "util_pct": round(util, 1) if util is not None else None,
            "status": status,
        })
    return pd.DataFrame(rows)
