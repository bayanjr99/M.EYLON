"""SQLite layer לנתוני שטח שמוזנים ידנית דרך המסך.

קובץ: data/project_control.sqlite (נפרד מ-audit.sqlite3 שמשמש לאוטומציה).

5 טבלאות, כל אחת עם המבנה הבסיסי:
    id              INTEGER PRIMARY KEY AUTOINCREMENT
    project_id      TEXT NOT NULL
    month           TEXT (MM-YYYY, נגזר אוטומטית מ-date)
    date            TEXT (YYYY-MM-DD)
    created_at      TEXT (ISO timestamp)
    updated_at      TEXT (ISO timestamp)
    source          TEXT (manual_entry / xlsx_import / ...)
    + עמודות ספציפיות לכל טבלה

אסטרטגיית persist:
    - bulk_save(table, df) - מקבל DataFrame מ-st.data_editor, מבצע upsert/insert/delete
    - מזהה שורות חדשות (id ריק) → insert
    - מזהה שורות קיימות (id) → update
    - שורות שנמחקו מ-DF (לעומת המקור) → delete
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "project_control.sqlite"


# ── Schema ────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS fuel_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    month           TEXT,
    date            TEXT,
    tool_name       TEXT,
    license_num     INTEGER,
    driver          TEXT,
    supplier        TEXT,
    invoice_num     TEXT,
    liters          REAL,
    price_per_liter REAL,
    total_cost      REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    source          TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_fuel_proj_month ON fuel_logs(project_id, month);
CREATE INDEX IF NOT EXISTS idx_fuel_license    ON fuel_logs(license_num);

CREATE TABLE IF NOT EXISTS equipment_work_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    month           TEXT,
    date            TEXT,
    tool_name       TEXT,
    license_num     INTEGER,
    operator        TEXT,
    work_hours      REAL,
    engine_hours    REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    source          TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_eqwl_proj_month ON equipment_work_logs(project_id, month);
CREATE INDEX IF NOT EXISTS idx_eqwl_license    ON equipment_work_logs(license_num);

CREATE TABLE IF NOT EXISTS employee_work_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    month           TEXT,
    date            TEXT,
    employee_name   TEXT,
    role            TEXT,
    hours           REAL,
    days            REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    source          TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_emp_proj_month ON employee_work_logs(project_id, month);
CREATE INDEX IF NOT EXISTS idx_emp_name       ON employee_work_logs(employee_name);

CREATE TABLE IF NOT EXISTS contractor_work_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    month           TEXT,
    date            TEXT,
    contractor_name TEXT,
    work_type       TEXT,
    quantity        REAL,
    hours           REAL,
    days            REAL,
    price           REAL,
    invoice_num     TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    source          TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_ctr_proj_month ON contractor_work_logs(project_id, month);
CREATE INDEX IF NOT EXISTS idx_ctr_name       ON contractor_work_logs(contractor_name);

CREATE TABLE IF NOT EXISTS maintenance_logs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         TEXT NOT NULL,
    month              TEXT,
    date               TEXT,
    tool_name          TEXT,
    license_num        INTEGER,
    treatment_type     TEXT,
    garage_supplier    TEXT,
    cost               REAL,
    engine_hours       REAL,
    next_service_hours REAL,
    invoice_num        TEXT,
    notes              TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    source             TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_maint_proj_month ON maintenance_logs(project_id, month);
CREATE INDEX IF NOT EXISTS idx_maint_license    ON maintenance_logs(license_num);

-- Import history with content-hash dedup
CREATE TABLE IF NOT EXISTS imported_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    month           TEXT,
    file_name       TEXT NOT NULL,
    file_path       TEXT,
    file_hash       TEXT UNIQUE,    -- SHA-256 of file content; same content = same import
    file_type       TEXT,           -- chashbashevet / balance / solar / hours / site_tracking / ...
    file_size_kb    INTEGER,
    rows_loaded     INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'imported',  -- imported / failed / skipped
    error_message   TEXT,
    imported_at     TEXT NOT NULL,
    imported_by     TEXT DEFAULT 'user'
);
CREATE INDEX IF NOT EXISTS idx_imp_proj_month ON imported_files(project_id, month);
CREATE INDEX IF NOT EXISTS idx_imp_hash       ON imported_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_imp_time       ON imported_files(imported_at);

-- QA findings — persisted so user can mark "resolved" and track history
CREATE TABLE IF NOT EXISTS data_quality_issues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL,
    month           TEXT,
    check_type      TEXT NOT NULL,   -- unmapped_account / orphan_supplier / duplicate / fuel_no_tool / ...
    severity        TEXT,            -- high / medium / low
    entity          TEXT,            -- account_num / supplier / license_num / ...
    details         TEXT,
    estimated_impact_nis REAL,
    status          TEXT DEFAULT 'open',  -- open / reviewed / resolved / dismissed
    resolved_at     TEXT,
    resolved_by     TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_proj_month ON data_quality_issues(project_id, month);
CREATE INDEX IF NOT EXISTS idx_dq_status     ON data_quality_issues(status);
CREATE INDEX IF NOT EXISTS idx_dq_check      ON data_quality_issues(check_type);

-- Fleet-wide tools registry (NOT per-project — same fleet works across sites).
-- Mirrors data/tools_registry.xlsx but mutable from the UI.
CREATE TABLE IF NOT EXISTS tools_registry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    license_num   INTEGER UNIQUE NOT NULL,
    tool_name     TEXT NOT NULL,
    tool_type     TEXT,
    owner         TEXT,
    norm_low      REAL,
    norm_high     REAL,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    source        TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_tools_license ON tools_registry(license_num);
"""

# מטא-נתונים לטבלאות (סדר עמודות לתצוגה + עמודות עברית)
TABLES: dict[str, dict] = {
    "fuel_logs": {
        "label": "יומן סולר",
        "user_columns": [
            ("date", "תאריך", "date"),
            ("tool_name", "כלי / רכב", "text"),
            ("license_num", "מס' רישוי", "int"),
            ("driver", "נהג / מפעיל", "text"),
            ("supplier", "ספק", "text"),
            ("invoice_num", "מספר חשבונית", "text"),
            ("liters", "ליטרים", "float"),
            ("price_per_liter", "₪ לליטר", "float"),
            ("total_cost", "סה\"כ עלות (₪)", "float"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "license_num", "liters"],
    },
    "equipment_work_logs": {
        "label": "שעות עבודה כלים",
        "user_columns": [
            ("date", "תאריך", "date"),
            ("tool_name", "כלי / רכב", "text"),
            ("license_num", "מס' רישוי", "int"),
            ("operator", "מפעיל", "text"),
            ("work_hours", "שעות עבודה", "float"),
            ("engine_hours", "שעות מנוע", "float"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "license_num", "work_hours"],
    },
    "employee_work_logs": {
        "label": "עובדים",
        "user_columns": [
            ("date", "תאריך", "date"),
            ("employee_name", "שם עובד", "text"),
            ("role", "תפקיד", "text"),
            ("hours", "שעות", "float"),
            ("days", "ימים", "float"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "employee_name"],
    },
    "contractor_work_logs": {
        "label": "קבלני משנה",
        "user_columns": [
            ("date", "תאריך", "date"),
            ("contractor_name", "שם קבלן", "text"),
            ("work_type", "סוג עבודה", "text"),
            ("quantity", "כמות", "float"),
            ("hours", "שעות", "float"),
            ("days", "ימים", "float"),
            ("price", "מחיר (₪)", "float"),
            ("invoice_num", "מספר חשבונית", "text"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "contractor_name"],
    },
    "maintenance_logs": {
        "label": "טיפולים ואחזקה",
        "user_columns": [
            ("date", "תאריך", "date"),
            ("tool_name", "כלי / רכב", "text"),
            ("license_num", "מס' רישוי", "int"),
            ("treatment_type", "סוג טיפול", "text"),
            ("garage_supplier", "מוסך / ספק", "text"),
            ("cost", "עלות (₪)", "float"),
            ("engine_hours", "שעות מנוע", "float"),
            ("next_service_hours", "טיפול הבא (שעות)", "float"),
            ("invoice_num", "מספר חשבונית", "text"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "license_num", "treatment_type"],
    },
}


# ── Connection / Init ─────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """יוצר את הסכמה (idempotent)."""
    with _connect() as conn:
        conn.executescript(SCHEMA)
    logger.info("control_db initialized at %s", DB_PATH)


# ── CRUD גנרי ────────────────────────────────────────────────
def list_rows(table: str, project_id: str,
              month: str | None = None,
              license_num: int | None = None,
              name_search: str | None = None) -> pd.DataFrame:
    """מחזיר שורות לפי project_id + פילטרים אופציונליים."""
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    init()
    sql = f"SELECT * FROM {table} WHERE project_id = ?"
    params: list = [project_id]
    if month:
        sql += " AND month = ?"
        params.append(month)
    if license_num is not None and "license_num" in {c[0] for c in TABLES[table]["user_columns"]}:
        sql += " AND license_num = ?"
        params.append(license_num)
    sql += " ORDER BY date DESC, id DESC"
    with _connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def validate_row(table: str, row: dict) -> list[str]:
    """מחזיר רשימת שגיאות validation לשורה (ריק = תקין)."""
    if table not in TABLES:
        return [f"Unknown table: {table}"]
    errors = []
    required = TABLES[table]["required"]
    for field in required:
        v = row.get(field)
        if v is None or (isinstance(v, str) and not v.strip()) or pd.isna(v):
            errors.append(f"שדה חובה חסר: {field}")
    return errors


def _month_from_date(date_val) -> str:
    """ממיר תאריך ל-MM-YYYY string."""
    try:
        dt = pd.to_datetime(date_val, errors="coerce")
        if pd.isna(dt):
            return ""
        return dt.strftime("%m-%Y")
    except Exception:
        return ""


def _normalize_row(table: str, row: dict, project_id: str) -> dict | None:
    """מנקה ומכין שורה ל-insert/update. מחזיר None אם validation נכשל."""
    out = {"project_id": project_id}
    for col, _, kind in TABLES[table]["user_columns"]:
        v = row.get(col)
        if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and pd.isna(v)):
            out[col] = None
        elif kind == "int":
            try:
                out[col] = int(float(v))
            except (TypeError, ValueError):
                out[col] = None
        elif kind == "float":
            try:
                out[col] = float(v)
            except (TypeError, ValueError):
                out[col] = None
        elif kind == "date":
            dt = pd.to_datetime(v, errors="coerce")
            out[col] = dt.strftime("%Y-%m-%d") if pd.notna(dt) else None
        else:
            out[col] = str(v).strip()
    out["month"] = _month_from_date(out.get("date"))
    return out


def bulk_save(table: str, edited_df: pd.DataFrame, project_id: str,
              original_ids: set[int] | None = None) -> dict:
    """שומר DataFrame שהגיע מ-st.data_editor.

    Args:
        table: שם טבלה.
        edited_df: DataFrame כפי שערך המשתמש.
        project_id: ID של הפרויקט.
        original_ids: סט ה-IDs שהיו לפני העריכה (לזיהוי מחיקות).

    Returns:
        dict עם: inserted, updated, deleted, errors.
    """
    if table not in TABLES:
        return {"inserted": 0, "updated": 0, "deleted": 0,
                "errors": [f"Unknown table: {table}"]}

    init()
    now = datetime.now().isoformat(timespec="seconds")
    inserted = updated = 0
    errors: list[str] = []
    user_cols = [c[0] for c in TABLES[table]["user_columns"]]
    current_ids = set()

    with _connect() as conn:
        for idx, row in edited_df.iterrows():
            row_dict = row.to_dict()
            row_id = row_dict.get("id")
            # Validation
            errs = validate_row(table, row_dict)
            if errs:
                errors.append(f"שורה {idx + 1}: {', '.join(errs)}")
                continue

            normalized = _normalize_row(table, row_dict, project_id)
            normalized["updated_at"] = now

            if row_id is None or pd.isna(row_id):
                # Insert
                normalized["created_at"] = now
                cols = ["project_id", "month", "created_at", "updated_at"] + user_cols
                placeholders = ", ".join(["?"] * len(cols))
                conn.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                    [normalized.get(c) for c in cols],
                )
                inserted += 1
            else:
                # Update
                current_ids.add(int(row_id))
                set_clause = ", ".join(f"{c} = ?" for c in user_cols + ["month", "updated_at"])
                conn.execute(
                    f"UPDATE {table} SET {set_clause} WHERE id = ? AND project_id = ?",
                    [normalized.get(c) for c in user_cols + ["month", "updated_at"]]
                    + [int(row_id), project_id],
                )
                updated += 1

        # Delete: rows that were in original_ids but no longer in current_ids
        deleted = 0
        if original_ids:
            removed = original_ids - current_ids
            for rid in removed:
                conn.execute(f"DELETE FROM {table} WHERE id = ? AND project_id = ?",
                             [rid, project_id])
                deleted += 1

    return {"inserted": inserted, "updated": updated,
            "deleted": deleted, "errors": errors}


def delete_row(table: str, row_id: int, project_id: str) -> bool:
    """מחיקה ישירה של שורה."""
    if table not in TABLES:
        return False
    init()
    with _connect() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ? AND project_id = ?",
                           [row_id, project_id])
        return cur.rowcount > 0


# ── Tools registry CRUD (fleet-wide, no project_id) ────────────
def list_tools() -> pd.DataFrame:
    """כל הכלים מ-SQLite. ממוין לפי license_num."""
    init()
    with _connect() as conn:
        return pd.read_sql(
            "SELECT * FROM tools_registry ORDER BY license_num",
            conn,
        )


def add_tool(license_num: int, tool_name: str, tool_type: str = "",
             owner: str = "", norm_low: float | None = None,
             norm_high: float | None = None, notes: str = "") -> tuple[bool, str]:
    """מוסיף כלי חדש. מחזיר (success, message)."""
    if not license_num:
        return False, "מספר רישוי חובה"
    if not tool_name or not tool_name.strip():
        return False, "שם כלי חובה"
    init()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO tools_registry
                   (license_num, tool_name, tool_type, owner, norm_low, norm_high,
                    notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (int(license_num), tool_name.strip(), tool_type.strip() or None,
                 owner.strip() or None, norm_low, norm_high,
                 notes.strip() or None, now, now),
            )
        return True, f"הכלי {license_num} נוסף"
    except sqlite3.IntegrityError:
        return False, f"מספר רישוי {license_num} כבר קיים"


def delete_tool_by_license(license_num: int) -> bool:
    """מחיקת כלי לפי license_num."""
    init()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM tools_registry WHERE license_num = ?", [int(license_num)]
        )
        return cur.rowcount > 0


def update_tool(license_num: int, **fields) -> bool:
    """עדכון שדות בכלי. השדות המותרים: tool_name, tool_type, owner, norm_low, norm_high, notes."""
    allowed = {"tool_name", "tool_type", "owner", "norm_low", "norm_high", "notes"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return False
    init()
    now = datetime.now().isoformat(timespec="seconds")
    set_clause = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
    params = list(fields.values()) + [now, int(license_num)]
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE tools_registry SET {set_clause} WHERE license_num = ?", params
        )
        return cur.rowcount > 0


def merged_tools_registry(xlsx_path: str | Path | None = None) -> pd.DataFrame:
    """ממזג tools_registry.xlsx + SQLite tools_registry.

    SQLite גובר על xlsx במקרה של חפיפה (license_num זהה).
    שימושי ל-pipeline._load_tools_registry().
    """
    sqlite_tools = list_tools()
    xlsx_tools = pd.DataFrame()
    if xlsx_path:
        try:
            xlsx_tools = pd.read_excel(xlsx_path, engine="openpyxl")
            xlsx_tools["license_num"] = pd.to_numeric(
                xlsx_tools["license_num"], errors="coerce"
            ).astype("Int64")
        except Exception as e:
            logger.warning("Failed to load tools xlsx: %s", e)
    if xlsx_tools.empty:
        return sqlite_tools
    if sqlite_tools.empty:
        return xlsx_tools
    # SQLite overrides xlsx for matching license_num
    sqlite_lics = set(sqlite_tools["license_num"].dropna().astype(int).tolist())
    xlsx_only = xlsx_tools[~xlsx_tools["license_num"].isin(sqlite_lics)]
    return pd.concat([xlsx_only, sqlite_tools], ignore_index=True, sort=False)


def count_rows(project_id: str) -> dict[str, int]:
    """מחזיר ספירת שורות לכל טבלה לפרויקט נתון."""
    init()
    out = {}
    with _connect() as conn:
        for table in TABLES:
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", [project_id]
            ).fetchone()[0]
            out[table] = int(n)
    return out
