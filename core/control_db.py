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

-- Fuel inventory entries (in-app entry of opening/closing per month per fuel_type)
-- אופציונלית - יכול לדור-בצד עם data/projects/<id>/<month>/fuel_inventory.xlsx
CREATE TABLE IF NOT EXISTS fuel_inventory_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    month       TEXT NOT NULL,            -- MM-YYYY
    fuel_type   TEXT NOT NULL DEFAULT 'סולר צמ"ה',
    tank_id     TEXT,                     -- מזהה מיכל (אם יש כמה)
    opening_l   REAL,
    closing_l   REAL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(project_id, month, fuel_type, tank_id)
);
CREATE INDEX IF NOT EXISTS idx_finv_proj_month ON fuel_inventory_entries(project_id, month);

-- Projects master (mirror of projects_registry.xlsx, mutable from UI)
CREATE TABLE IF NOT EXISTS projects (
    project_id      TEXT PRIMARY KEY,
    project_name    TEXT NOT NULL,
    site_name       TEXT,
    status          TEXT DEFAULT 'active',
    start_date      TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Suppliers master (derived from chashbashevet, with manual category overrides)
CREATE TABLE IF NOT EXISTS suppliers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name     TEXT UNIQUE NOT NULL,
    primary_category  TEXT,
    notes             TEXT,
    manual_override   INTEGER DEFAULT 0,  -- 1 if user explicitly set category
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sup_category ON suppliers(primary_category);

-- Fleet-wide tools registry (NOT per-project — same fleet works across sites).
-- Mirrors data/tools_registry.xlsx but mutable from the UI.
-- Acts as the "equipment" central table — all fuel/hours/maintenance
-- records cross-reference via license_num.
CREATE TABLE IF NOT EXISTS tools_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    license_num     INTEGER UNIQUE NOT NULL,
    internal_num    TEXT,                -- מספר פנימי (לא רישוי)
    tool_name       TEXT NOT NULL,
    tool_type       TEXT,
    equipment_group TEXT DEFAULT 'אחר',  -- צמ"ה / רכב / משאית / חשמלי / אחר
    fuel_type       TEXT,                -- סולר / בנזין / חשמל / לא רלוונטי
    ownership       TEXT DEFAULT 'בעלים',-- בעלים / שכירות / קבלן משנה
    status          TEXT DEFAULT 'פעיל', -- פעיל / לא פעיל / בטיפול
    owner           TEXT,
    norm_low        REAL,
    norm_high       REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    source          TEXT DEFAULT 'manual_entry'
);
CREATE INDEX IF NOT EXISTS idx_tools_license ON tools_registry(license_num);
-- equipment_group index created in _migrate_tools_registry after column exists
"""

# Valid values for the new fields (used by UI dropdowns + validation)
EQUIPMENT_GROUPS = ["צמ\"ה", "רכב", "משאית", "חשמלי", "אחר"]
FUEL_TYPES = ["סולר", "בנזין", "חשמל", "לא רלוונטי"]
OWNERSHIPS = ["בעלים", "שכירות", "קבלן משנה"]
EQUIPMENT_STATUSES = ["פעיל", "לא פעיל", "בטיפול"]

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


def _migrate_tools_registry(conn: sqlite3.Connection) -> None:
    """מוסיף עמודות חדשות ל-tools_registry אם הן חסרות (תאימות לאחור).

    SQLite לא תומך ב-ADD COLUMN IF NOT EXISTS, לכן בודקים PRAGMA קודם.
    """
    existing = {r[1] for r in conn.execute("PRAGMA table_info(tools_registry)").fetchall()}
    to_add = {
        "internal_num": "TEXT",
        "equipment_group": "TEXT DEFAULT 'אחר'",
        "fuel_type": "TEXT",
        "ownership": "TEXT DEFAULT 'בעלים'",
        "status": "TEXT DEFAULT 'פעיל'",
    }
    for col, type_def in to_add.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE tools_registry ADD COLUMN {col} {type_def}")
                logger.info("Migrated tools_registry: added column %s", col)
            except sqlite3.OperationalError as e:
                logger.warning("Migration failed for %s: %s", col, e)
    # Create equipment_group index now that the column exists
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_group ON tools_registry(equipment_group)")
    except sqlite3.OperationalError:
        pass


def init() -> None:
    """יוצר את הסכמה (idempotent) + migrations."""
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate_tools_registry(conn)
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
             norm_high: float | None = None, notes: str = "",
             internal_num: str = "", equipment_group: str = "אחר",
             fuel_type: str = "", ownership: str = "בעלים",
             status: str = "פעיל") -> tuple[bool, str]:
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
                   (license_num, internal_num, tool_name, tool_type, equipment_group,
                    fuel_type, ownership, status, owner, norm_low, norm_high,
                    notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (int(license_num), internal_num.strip() or None,
                 tool_name.strip(), tool_type.strip() or None,
                 equipment_group or "אחר",
                 fuel_type.strip() or None,
                 ownership or "בעלים",
                 status or "פעיל",
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
    """עדכון שדות בכלי. כולל את כל השדות החדשים."""
    allowed = {"tool_name", "tool_type", "owner", "norm_low", "norm_high", "notes",
               "internal_num", "equipment_group", "fuel_type", "ownership", "status"}
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


# ── Projects mirror (from projects_registry.xlsx) ──────────────
def sync_projects_from_xlsx(xlsx_path: str | Path) -> int:
    """Mirror projects_registry.xlsx → projects table.

    Idempotent upsert. Returns the number of projects upserted.
    """
    init()
    path = Path(xlsx_path)
    if not path.exists():
        return 0
    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    with _connect() as conn:
        for _, r in df.iterrows():
            pid = str(r.get("project_id", "") or "").strip()
            if not pid:
                continue
            existing = conn.execute(
                "SELECT project_id FROM projects WHERE project_id = ?", [pid]
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE projects SET project_name=?, site_name=?, status=?,
                       start_date=?, notes=?, updated_at=? WHERE project_id=?""",
                    [str(r.get("project_name", "") or ""),
                     str(r.get("site_name", "") or ""),
                     str(r.get("status", "active") or "active"),
                     str(r.get("start_date", "") or ""),
                     str(r.get("notes", "") or ""), now, pid],
                )
            else:
                conn.execute(
                    """INSERT INTO projects (project_id, project_name, site_name,
                       status, start_date, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [pid, str(r.get("project_name", "") or ""),
                     str(r.get("site_name", "") or ""),
                     str(r.get("status", "active") or "active"),
                     str(r.get("start_date", "") or ""),
                     str(r.get("notes", "") or ""), now, now],
                )
            n += 1
    return n


def list_projects() -> pd.DataFrame:
    """כל הפרויקטים מהטבלה."""
    init()
    with _connect() as conn:
        return pd.read_sql("SELECT * FROM projects ORDER BY project_id", conn)


# ── Suppliers mirror ───────────────────────────────────────────
def sync_suppliers_from_master(df_master: pd.DataFrame) -> int:
    """מוסיף ספקים חדשים שמופיעים ב-master, בלי לדרוס overrides ידניים."""
    if df_master.empty or "supplier" not in df_master.columns:
        return 0
    init()
    # Derive category per supplier (dominant by amount)
    exp = df_master[df_master["amount"] > 0] if "amount" in df_master.columns else df_master
    exp = exp[exp["supplier"].fillna("").astype(str).str.strip() != ""]
    if exp.empty:
        return 0
    sc = exp.groupby(["supplier", "category"])["amount"].sum().reset_index()
    primary = sc.sort_values("amount", ascending=False).drop_duplicates(subset=["supplier"])
    primary = dict(zip(primary["supplier"], primary["category"]))

    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    with _connect() as conn:
        for sup, cat in primary.items():
            existing = conn.execute(
                "SELECT id, manual_override FROM suppliers WHERE supplier_name = ?",
                [sup],
            ).fetchone()
            if existing:
                # only update category if no manual override
                if not existing["manual_override"]:
                    conn.execute(
                        "UPDATE suppliers SET primary_category=?, updated_at=? WHERE id=?",
                        [cat, now, existing["id"]],
                    )
            else:
                conn.execute(
                    """INSERT INTO suppliers
                       (supplier_name, primary_category, manual_override, created_at, updated_at)
                       VALUES (?, ?, 0, ?, ?)""",
                    [sup, cat, now, now],
                )
                n += 1
    return n


def list_suppliers() -> pd.DataFrame:
    init()
    with _connect() as conn:
        return pd.read_sql(
            "SELECT * FROM suppliers ORDER BY primary_category, supplier_name",
            conn,
        )


# ── Fuel inventory CRUD ───────────────────────────────────────
def list_fuel_inventory(project_id: str, month: str | None = None,
                          fuel_type: str | None = None) -> pd.DataFrame:
    """רשימת רישומי מלאי לפרויקט."""
    init()
    sql = "SELECT * FROM fuel_inventory_entries WHERE project_id = ?"
    params = [project_id]
    if month:
        sql += " AND month = ?"
        params.append(month)
    if fuel_type:
        sql += " AND fuel_type = ?"
        params.append(fuel_type)
    sql += " ORDER BY month, fuel_type, tank_id"
    with _connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def save_fuel_inventory(project_id: str, month: str, fuel_type: str = "סולר צמ\"ה",
                          opening_l: float | None = None,
                          closing_l: float | None = None,
                          tank_id: str = "", notes: str = "") -> tuple[bool, str]:
    """upsert של רישום מלאי. UNIQUE על (project, month, fuel_type, tank)."""
    if not month:
        return False, "חודש חובה"
    if opening_l is None and closing_l is None:
        return False, "יש להזין לפחות מלאי פתיחה או סגירה"
    init()
    now = datetime.now().isoformat(timespec="seconds")
    tank_norm = (tank_id or "").strip() or None
    try:
        with _connect() as conn:
            existing = conn.execute(
                """SELECT id FROM fuel_inventory_entries
                   WHERE project_id = ? AND month = ? AND fuel_type = ?
                   AND COALESCE(tank_id,'') = COALESCE(?, '')""",
                [project_id, month, fuel_type, tank_norm or ""],
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE fuel_inventory_entries SET
                       opening_l=?, closing_l=?, notes=?, updated_at=?
                       WHERE id=?""",
                    [opening_l, closing_l, notes, now, existing["id"]],
                )
                return True, f"עודכן: {month} {fuel_type}"
            conn.execute(
                """INSERT INTO fuel_inventory_entries
                   (project_id, month, fuel_type, tank_id, opening_l, closing_l,
                    notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [project_id, month, fuel_type, tank_norm,
                 opening_l, closing_l, notes, now, now],
            )
            return True, f"נוסף: {month} {fuel_type}"
    except sqlite3.IntegrityError as e:
        return False, f"שגיאה: {e}"


def delete_fuel_inventory(entry_id: int, project_id: str) -> bool:
    init()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM fuel_inventory_entries WHERE id = ? AND project_id = ?",
            [entry_id, project_id],
        )
        return cur.rowcount > 0


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
