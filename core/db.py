"""שכבת SQLite לאחסון מאסטר + audit log + הערות.

קיים במקביל ל-master.parquet — לא מחליף אותו (parquet נשאר primary
כי הוא 30KB ועובד טוב ב-Streamlit Cloud). SQLite משמש ל:
    1. שאילתות מורכבות שמאתגרות parquet (filter pushdown, joins)
    2. audit log — מתי נטען איזה חודש ע"י מי
    3. הערות משתמש על תנועות (לעתיד)

שימוש:
    from core import db
    db.init()                            # יצירת סכמה אם לא קיימת
    db.upsert_master(master_df)          # החלפה של כל המאסטר
    rows = db.query_project('rishon_letzion', month='12-2025')
    db.log_event('build_master', {...})
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.sqlite3"


# ── Schema ─────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    project_name    TEXT,
    month           TEXT,           -- MM-YYYY
    date            TEXT,           -- ISO YYYY-MM-DD
    category        TEXT,
    subcategory     TEXT,
    account_num     INTEGER,
    account_name    TEXT,
    supplier        TEXT,
    description     TEXT,
    amount          REAL,
    source          TEXT,           -- chashbashevet / solar / hours / manual
    anomaly_flags   TEXT,
    license_num     INTEGER,
    tool_name       TEXT,
    liters          REAL,
    engine_hours    REAL,
    work_hours      REAL
);

CREATE INDEX IF NOT EXISTS idx_tx_project    ON transactions(project_id);
CREATE INDEX IF NOT EXISTS idx_tx_month      ON transactions(month);
CREATE INDEX IF NOT EXISTS idx_tx_proj_month ON transactions(project_id, month);
CREATE INDEX IF NOT EXISTS idx_tx_category   ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_tx_supplier   ON transactions(supplier);
CREATE INDEX IF NOT EXISTS idx_tx_license    ON transactions(license_num);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,           -- ISO
    event       TEXT NOT NULL,           -- build_master / month_imported / month_deleted / ...
    details     TEXT                     -- JSON blob with arbitrary metadata
);

CREATE INDEX IF NOT EXISTS idx_audit_time  ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event);

CREATE TABLE IF NOT EXISTS transaction_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  INTEGER,
    project_id      TEXT,
    account_num     INTEGER,
    date            TEXT,
    note            TEXT NOT NULL,
    author          TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,           -- ISO upload time
    project_id      TEXT,
    project_name    TEXT,
    report_type     TEXT,                    -- ledger / balance
    file_name       TEXT,
    report_date     TEXT,                    -- ISO report/update date
    source          TEXT,                    -- chashbashevet / manual / other
    mode            TEXT,                    -- add_new / replace_range / check_only
    rows_in_file    INTEGER,
    new_rows        INTEGER,
    duplicate_rows  INTEGER,
    updated_rows    INTEGER,
    error_rows      INTEGER,
    months_affected TEXT,                    -- comma-joined MM-YYYY
    status          TEXT,                    -- approved / checked / failed
    details         TEXT                     -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_import_proj ON import_log(project_id);
CREATE INDEX IF NOT EXISTS idx_import_time ON import_log(timestamp);
"""


def _connect() -> sqlite3.Connection:
    """מחזיר חיבור SQLite (יוצר את הקובץ אם לא קיים)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    """יוצר את הסכמה (idempotent)."""
    with _connect() as conn:
        conn.executescript(SCHEMA)
    logger.info("DB initialized at %s", DB_PATH)


def upsert_master(df: pd.DataFrame) -> int:
    """מחליף את כל הרשומות בטבלת transactions (truncate + insert).

    זו השיטה הפשוטה - מתאים לדאטה קטן (אלפי שורות) כשהוא נבנה
    מחדש בכל build_master. אם הסקייל יגדל אפשר לעבור ל-upsert לפי month.

    Returns: מספר השורות שהוכנסו.
    """
    if df.empty:
        logger.info("upsert_master called with empty df - skipping")
        return 0

    init()
    df = df.copy()
    # normalize date → ISO string
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    # ensure all schema columns exist
    schema_cols = [
        "project_id", "project_name", "month", "date", "category", "subcategory",
        "account_num", "account_name", "supplier", "description", "amount",
        "source", "anomaly_flags", "license_num", "tool_name", "liters",
        "engine_hours", "work_hours",
    ]
    for c in schema_cols:
        if c not in df.columns:
            df[c] = None
    df = df[schema_cols]

    # SQLite doesn't handle pd.NA — convert to None
    df = df.where(pd.notna(df), None)

    with _connect() as conn:
        conn.execute("DELETE FROM transactions")
        df.to_sql("transactions", conn, if_exists="append", index=False)
        n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    log_event("master_upserted", {"rows": int(n)})
    logger.info("Upserted %d rows into transactions", n)
    return int(n)


def query_project(project_id: str, month: str | None = None,
                   source: str | None = None) -> pd.DataFrame:
    """שאילתה ממוקדת לפרויקט. נתמך filter לפי חודש/מקור."""
    init()
    sql = "SELECT * FROM transactions WHERE project_id = ?"
    params: list = [project_id]
    if month:
        sql += " AND month = ?"
        params.append(month)
    if source:
        sql += " AND source = ?"
        params.append(source)
    with _connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def list_projects() -> list[str]:
    """רשימת project_ids ב-DB (לא ברגיסטרי)."""
    init()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT project_id FROM transactions ORDER BY project_id"
        ).fetchall()
    return [r[0] for r in rows]


def log_event(event: str, details: dict | None = None) -> None:
    """כותב שורת audit."""
    init()
    payload = json.dumps(details or {}, ensure_ascii=False, default=str)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, event, details) VALUES (?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), event, payload),
        )


def recent_events(limit: int = 50) -> pd.DataFrame:
    """מחזיר אירועי audit אחרונים."""
    init()
    with _connect() as conn:
        return pd.read_sql(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            conn, params=[limit],
        )


def log_import(project_id: str, project_name: str, report_type: str,
               file_name: str, report_date: str | None, source: str,
               mode: str, summary: dict, status: str) -> int:
    """רושם שורת היסטוריית יבוא. מחזיר import_id.

    Args:
        report_type: 'ledger' (כרטסת) או 'balance' (מאזן).
        summary: ה-dict מ-ledger_store.analyze/apply_import.
        status: 'approved' / 'checked' / 'failed'.
    """
    init()
    months = summary.get("months", []) or []
    payload = json.dumps({
        "date_min": str(summary.get("date_min", "")),
        "date_max": str(summary.get("date_max", "")),
        "debit_sum": summary.get("debit_sum", 0),
        "credit_sum": summary.get("credit_sum", 0),
        "store_before": summary.get("store_before", 0),
        "store_after": summary.get("store_after", 0),
    }, ensure_ascii=False, default=str)
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO import_log
               (timestamp, project_id, project_name, report_type, file_name,
                report_date, source, mode, rows_in_file, new_rows,
                duplicate_rows, updated_rows, error_rows, months_affected,
                status, details)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now().isoformat(timespec="seconds"),
                project_id, project_name, report_type, file_name,
                report_date, source, mode,
                int(summary.get("rows_in_file", 0)),
                int(summary.get("new_count", 0)),
                int(summary.get("duplicate_count", 0)),
                int(summary.get("updated_count", 0)),
                int(summary.get("no_date_count", 0) + summary.get("no_amount_count", 0)),
                ", ".join(months),
                status, payload,
            ),
        )
        return int(cur.lastrowid)


def import_history(project_id: str | None = None, limit: int = 100) -> pd.DataFrame:
    """מחזיר היסטוריית יבוא (אופציונלית מסוננת לפרויקט)."""
    init()
    sql = "SELECT * FROM import_log"
    params: list = []
    if project_id:
        sql += " WHERE project_id = ?"
        params.append(project_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def add_note(project_id: str, account_num: int | None, date: str | None,
              note: str, author: str = "user") -> int:
    """מוסיף הערה לתנועה. מחזיר את note_id."""
    init()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO transaction_notes
               (project_id, account_num, date, note, author, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, account_num, date, note, author,
             datetime.now().isoformat(timespec="seconds")),
        )
        return int(cur.lastrowid)


def get_notes(project_id: str) -> pd.DataFrame:
    """מחזיר הערות לפרויקט."""
    init()
    with _connect() as conn:
        return pd.read_sql(
            "SELECT * FROM transaction_notes WHERE project_id = ? ORDER BY id DESC",
            conn, params=[project_id],
        )
