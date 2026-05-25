"""שכבת אחסון מאוחדת - facade לכל המאגרים.

מסתיר את הפיצול בין:
    - data/master.parquet           - תנועות חשבשבת מעובדות
    - data/site_tracking.parquet    - נתונים תפעוליים מ-site_tracking.xlsx
    - data/project_control.sqlite   - תקציב, manual entries, imported_files,
                                       data_quality_issues, tools_registry
    - data/audit.sqlite3            - mirror של master + audit_log

מספק API ברמה גבוהה ותואם למפרט המשתמש:
    init_db, save_imported_file, load_project_data, save_transactions,
    save_manual_entries, delete_project_month, prevent_duplicate_import,
    list_imported_files, backup_database.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ── Paths ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
DB_CONTROL = DATA_ROOT / "project_control.sqlite"
DB_AUDIT = DATA_ROOT / "audit.sqlite3"
MASTER_PARQUET = DATA_ROOT / "master.parquet"
SITE_TRACKING_PARQUET = DATA_ROOT / "site_tracking.parquet"
PROJECTS_ROOT = DATA_ROOT / "projects"
BACKUP_ROOT = DATA_ROOT / "backups"


# ── Core init ────────────────────────────────────────────────
def init_db() -> None:
    """יוצר את כל הסכמות בכל ה-SQLite-ים (idempotent)."""
    from core import control_db, db, budget_db
    control_db.init()
    budget_db.init()
    db.init()
    logger.info("All databases initialized")


# ── File hashing & dedup ─────────────────────────────────────
def _file_sha256(file_path: str | Path) -> str:
    """מחשב SHA-256 של קובץ. משמש לזיהוי כפילויות."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def prevent_duplicate_import(file_path: str | Path) -> dict | None:
    """בודק אם קובץ עם אותו תוכן כבר יובא.

    Returns dict עם פרטי הייבוא הקודם אם קיים, אחרת None.
    """
    init_db()
    file_path = Path(file_path)
    if not file_path.exists():
        return None
    h = _file_sha256(file_path)
    with sqlite3.connect(DB_CONTROL) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM imported_files WHERE file_hash = ?", [h]
        ).fetchone()
    return dict(row) if row else None


# ── Imported files registry ──────────────────────────────────
def save_imported_file(file_path: str | Path, project_id: str, month: str,
                        file_type: str, rows_loaded: int = 0,
                        error_count: int = 0, status: str = "imported",
                        error_message: str = "", imported_by: str = "user") -> int:
    """רושם קובץ שיובא ב-imported_files. מחזיר id חדש או id קיים אם duplicate.

    אם hash כבר קיים — מעדכן את הרשומה הקיימת עם זמן ייבוא חדש.
    """
    init_db()
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("save_imported_file: %s does not exist", file_path)
        file_hash = None
        file_size_kb = 0
    else:
        file_hash = _file_sha256(file_path)
        file_size_kb = file_path.stat().st_size // 1024

    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_CONTROL) as conn:
        conn.row_factory = sqlite3.Row
        existing = None
        if file_hash:
            existing = conn.execute(
                "SELECT id FROM imported_files WHERE file_hash = ?", [file_hash]
            ).fetchone()
        if existing:
            conn.execute(
                """UPDATE imported_files SET
                    project_id=?, month=?, file_name=?, file_path=?, file_type=?,
                    file_size_kb=?, rows_loaded=?, error_count=?, status=?,
                    error_message=?, imported_at=?, imported_by=?
                   WHERE id=?""",
                [project_id, month, file_path.name, str(file_path), file_type,
                 file_size_kb, rows_loaded, error_count, status,
                 error_message, now, imported_by, existing["id"]],
            )
            return int(existing["id"])
        else:
            cur = conn.execute(
                """INSERT INTO imported_files
                   (project_id, month, file_name, file_path, file_hash, file_type,
                    file_size_kb, rows_loaded, error_count, status, error_message,
                    imported_at, imported_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [project_id, month, file_path.name, str(file_path), file_hash,
                 file_type, file_size_kb, rows_loaded, error_count, status,
                 error_message, now, imported_by],
            )
            return int(cur.lastrowid)


def list_imported_files(project_id: str | None = None,
                         month: str | None = None) -> pd.DataFrame:
    """רשימת קבצים שיובאו, סינון אופציונלי."""
    init_db()
    sql = "SELECT * FROM imported_files WHERE 1=1"
    params = []
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    if month:
        sql += " AND month = ?"
        params.append(month)
    sql += " ORDER BY imported_at DESC"
    with sqlite3.connect(DB_CONTROL) as conn:
        return pd.read_sql(sql, conn, params=params)


# ── Loading data for the UI ──────────────────────────────────
def load_project_data(project_id: str) -> dict[str, pd.DataFrame]:
    """טוען את כל הנתונים של פרויקט יחיד מכל המקורות.

    Returns dict עם:
        master         - מ-master.parquet, מסונן לפרויקט
        site_tracking  - dict של dfs מ-site_tracking.parquet
        budget         - מ-project_budget (SQLite)
        metadata       - מ-project_metadata (SQLite, או None)
        manual_logs    - dict עם 5 הטבלאות הידניות
        notes          - הערות תנועה מ-transaction_notes (אם יש)
        quality_issues - חריגות פתוחות מ-data_quality_issues
    """
    from pipeline import load_master, load_site_tracking_data
    from core import control_db, budget_db

    out: dict[str, Any] = {}
    master = load_master()
    out["master"] = master[master["project_id"] == project_id] if not master.empty else master

    out["site_tracking"] = load_site_tracking_data(project_id)

    out["budget"] = budget_db.get_budget(project_id)
    out["metadata"] = budget_db.get_metadata(project_id)

    out["manual_logs"] = {
        table: control_db.list_rows(table, project_id)
        for table in ["fuel_logs", "equipment_work_logs", "employee_work_logs",
                       "contractor_work_logs", "maintenance_logs"]
    }

    init_db()
    with sqlite3.connect(DB_CONTROL) as conn:
        out["quality_issues"] = pd.read_sql(
            "SELECT * FROM data_quality_issues WHERE project_id = ? AND status = 'open'",
            conn, params=[project_id],
        )

    return out


# ── Transaction persistence ──────────────────────────────────
def save_transactions(df: pd.DataFrame, source_file_id: int | None = None) -> int:
    """דוחף תנועות ל-audit.sqlite3.transactions (mirror של master).

    משמש את build_master. במקביל ל-parquet (כפי שכבר קורה ב-pipeline.build_master).
    """
    from core import db
    return db.upsert_master(df)


def save_manual_entries(table: str, df: pd.DataFrame, project_id: str) -> dict:
    """שמירת רשומות שהוזנו ידנית דרך field_data_entry.

    Wrapper על control_db.bulk_save שמוסיף logging.
    """
    from core import control_db
    result = control_db.bulk_save(table, df, project_id)
    logger.info("save_manual_entries %s/%s: %s", table, project_id, result)
    return result


# ── Project / month deletion ─────────────────────────────────
def delete_project_month(project_id: str, month: str,
                          delete_files: bool = False) -> dict:
    """מוחק את כל נתוני (project_id, month) מהמערכת.

    Args:
        delete_files: אם True, מוחק גם את קבצי ה-xlsx בתיקיית החודש.
                      ברירת מחדל False = שומר את הקבצים.

    Returns dict עם counts לכל טבלה.
    """
    init_db()
    counts = {}
    with sqlite3.connect(DB_CONTROL) as conn:
        for table in ["fuel_logs", "equipment_work_logs", "employee_work_logs",
                       "contractor_work_logs", "maintenance_logs",
                       "imported_files", "data_quality_issues"]:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE project_id = ? AND month = ?",
                [project_id, month],
            )
            counts[table] = cur.rowcount

    # Audit DB has transactions mirror
    if DB_AUDIT.exists():
        with sqlite3.connect(DB_AUDIT) as conn:
            cur = conn.execute(
                "DELETE FROM transactions WHERE project_id = ? AND month = ?",
                [project_id, month],
            )
            counts["transactions_audit"] = cur.rowcount

    if delete_files:
        month_dir = PROJECTS_ROOT / project_id / month
        if month_dir.exists():
            for f in month_dir.iterdir():
                if f.is_file():
                    f.unlink()
            counts["files_deleted"] = sum(1 for k, v in counts.items() if k.endswith("_deleted"))

    logger.info("delete_project_month %s/%s: %s", project_id, month, counts)
    return counts


# ── Backup ───────────────────────────────────────────────────
def backup_database(suffix: str | None = None) -> dict[str, Path]:
    """יוצר גיבוי של כל קובצי ה-SQLite + parquet עם timestamp.

    Returns dict {original_name → backup_path}.
    """
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = suffix or datetime.now().strftime("%Y%m%d_%H%M%S")
    out: dict[str, Path] = {}
    for src in [DB_CONTROL, DB_AUDIT, MASTER_PARQUET, SITE_TRACKING_PARQUET]:
        if not src.exists():
            continue
        dst = BACKUP_ROOT / f"{src.stem}_{stamp}{src.suffix}"
        shutil.copy2(src, dst)
        out[src.name] = dst
        logger.info("Backed up %s → %s", src.name, dst)
    return out


def list_backups() -> pd.DataFrame:
    """רשימת גיבויים שנשמרו."""
    if not BACKUP_ROOT.exists():
        return pd.DataFrame(columns=["file_name", "size_kb", "modified"])
    rows = []
    for f in sorted(BACKUP_ROOT.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not f.is_file():
            continue
        rows.append({
            "file_name": f.name,
            "size_kb": f.stat().st_size // 1024,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return pd.DataFrame(rows)


# ── Data quality issues persistence ──────────────────────────
def log_quality_issue(project_id: str, check_type: str, severity: str,
                        entity: str = "", details: str = "",
                        estimated_impact: float = 0, month: str = "") -> int:
    """כותב חריגה ל-data_quality_issues. מחזיר id."""
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_CONTROL) as conn:
        cur = conn.execute(
            """INSERT INTO data_quality_issues
               (project_id, month, check_type, severity, entity, details,
                estimated_impact_nis, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [project_id, month, check_type, severity, entity, details,
             estimated_impact, now, now],
        )
        return int(cur.lastrowid)


def mark_issue_resolved(issue_id: int, resolved_by: str = "user",
                          notes: str = "") -> bool:
    """מסמן חריגה כטופלה."""
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_CONTROL) as conn:
        cur = conn.execute(
            """UPDATE data_quality_issues
               SET status='resolved', resolved_at=?, resolved_by=?,
                   notes=COALESCE(notes,'') || ' | ' || ?, updated_at=?
               WHERE id=?""",
            [now, resolved_by, notes, now, issue_id],
        )
        return cur.rowcount > 0


def list_quality_issues(project_id: str | None = None,
                          status: str = "open") -> pd.DataFrame:
    """רשימת חריגות לפי סטטוס."""
    init_db()
    sql = "SELECT * FROM data_quality_issues WHERE 1=1"
    params = []
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    with sqlite3.connect(DB_CONTROL) as conn:
        return pd.read_sql(sql, conn, params=params)
