"""מאגר תצלומי מאזן בוחן (snapshots) לכל פרויקט.

המאזן נשמר כ-Snapshot לפי תאריך דוח — *לא* כתנועות. זה מונע כפילות:
הכרטסת היא מקור התנועות (ledger_store), המאזן הוא בקרה ויתרות-עד-תאריך.

אחסון:
    data/projects/<project_id>/_balance_snapshots.parquet

עמודות: report_date, account_num, account_name, debit, credit, balance,
         group, account_type, import_date, source_file.

כל העלאה של מאזן חדש לאותו report_date מחליפה את הקודם (idempotent).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


SNAPSHOT_COLS = [
    "report_date", "account_num", "account_name", "debit", "credit",
    "balance", "group", "account_type", "import_date", "source_file",
]


def _snap_path(project_id: str) -> Path:
    from pipeline import PROJECTS_ROOT
    return PROJECTS_ROOT / project_id / "_balance_snapshots.parquet"


def classify_account_type(account_num, group: str, account_name: str) -> str:
    """סיווג גס של סוג חשבון: הכנסות / הוצאות / נכסים / התחייבויות / הון.

    מבוסס על טווחי מספרי חשבון מקובלים בחשבשבת + מילות מפתח בשם.
    משמש לבקרה בלבד (לא מחייב דיוק חשבונאי מלא).
    """
    from utils.hebrew import match_normalize
    from core.chashbashevet_loader import INCOME_ACCOUNTS

    try:
        num = int(float(account_num))
    except (TypeError, ValueError):
        num = None

    name_n = match_normalize(account_name or "")
    group_n = match_normalize(group or "")

    if num in INCOME_ACCOUNTS or "הכנסות" in name_n or "הכנסות" in group_n:
        return "הכנסות"
    if num is not None:
        # מוסכמה נפוצה: 1xxx-3xxx מאזן (נכסים/התחייבויות/הון), 4xxx+ תוצאתי
        if 1000 <= num < 2000:
            return "נכסים"
        if 2000 <= num < 3000:
            return "התחייבויות"
        if 3000 <= num < 4000:
            return "הון"
        if num >= 4000:
            return "הוצאות"
    if any(k in name_n for k in ("הוצאות", "עלות", "רכש", "קבלן")):
        return "הוצאות"
    if any(k in name_n for k in ("בנק", "קופה", "לקוחות", "מלאי")):
        return "נכסים"
    if any(k in name_n for k in ("ספקים", "הלוואות", "זכאים")):
        return "התחייבויות"
    return "אחר"


def load_snapshots(project_id: str) -> pd.DataFrame:
    """טוען את כל תצלומי המאזן של הפרויקט. ריק אם אין."""
    path = _snap_path(project_id)
    if not path.exists():
        return pd.DataFrame(columns=SNAPSHOT_COLS)
    try:
        df = pd.read_parquet(path)
        if "report_date" in df.columns:
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        return df
    except Exception as e:
        logger.exception("Failed to load balance snapshots %s: %s", path, e)
        return pd.DataFrame(columns=SNAPSHOT_COLS)


def list_snapshot_dates(project_id: str) -> list:
    """רשימת תאריכי דוח (report_date) שקיימים במאגר, ממוין יורד."""
    df = load_snapshots(project_id)
    if df.empty:
        return []
    dates = pd.to_datetime(df["report_date"], errors="coerce").dropna().unique()
    return sorted(dates, reverse=True)


def save_snapshot(project_id: str, balance_df: pd.DataFrame,
                  report_date, source_file: str = "") -> int:
    """שומר תצלום מאזן לתאריך דוח נתון. מחליף תצלום קיים לאותו תאריך.

    Args:
        project_id: מזהה הפרויקט.
        balance_df: פלט balance_loader.load_balance.
        report_date: תאריך הדוח (datetime / str / date).
        source_file: שם הקובץ המקורי.

    Returns:
        מספר שורות החשבונות שנשמרו בתצלום.
    """
    if balance_df is None or balance_df.empty:
        return 0

    rd = pd.to_datetime(report_date, errors="coerce")
    if pd.isna(rd):
        rd = pd.Timestamp(datetime.now().date())
    rd_norm = rd.normalize()

    snap = balance_df.copy()
    snap["report_date"] = rd_norm
    snap["import_date"] = datetime.now().strftime("%Y-%m-%d")
    snap["source_file"] = source_file
    snap["account_type"] = snap.apply(
        lambda r: classify_account_type(
            r.get("account_num"), r.get("group", ""), r.get("account_name", ""),
        ), axis=1,
    )
    for c in SNAPSHOT_COLS:
        if c not in snap.columns:
            snap[c] = pd.NA
    snap = snap[SNAPSHOT_COLS]

    existing = load_snapshots(project_id)
    if not existing.empty:
        # הסר תצלום קיים לאותו תאריך דוח
        ex_dt = pd.to_datetime(existing["report_date"], errors="coerce").dt.normalize()
        existing = existing.loc[ex_dt != rd_norm]
        merged = pd.concat([existing, snap], ignore_index=True, sort=False)
    else:
        merged = snap

    path = _snap_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        merged.to_parquet(path, index=False)
        logger.info("Saved balance snapshot %s (%d accounts) for %s",
                    rd_norm.date(), len(snap), project_id)
    except Exception as e:
        logger.exception("Failed to save balance snapshot: %s", e)
    return len(snap)


def latest_snapshot(project_id: str) -> pd.DataFrame:
    """מחזיר את התצלום העדכני ביותר (לפי report_date)."""
    df = load_snapshots(project_id)
    if df.empty:
        return df
    dt = pd.to_datetime(df["report_date"], errors="coerce")
    latest = dt.max()
    return df.loc[dt == latest].reset_index(drop=True)


def get_snapshot(project_id: str, report_date) -> pd.DataFrame:
    """מחזיר תצלום לתאריך דוח ספציפי."""
    df = load_snapshots(project_id)
    if df.empty:
        return df
    rd = pd.to_datetime(report_date, errors="coerce").normalize()
    dt = pd.to_datetime(df["report_date"], errors="coerce").dt.normalize()
    return df.loc[dt == rd].reset_index(drop=True)


def delete_snapshots(project_id: str) -> bool:
    """מוחק את כל תצלומי המאזן של הפרויקט."""
    path = _snap_path(project_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception as e:
            logger.warning("Failed to delete balance snapshots: %s", e)
    return False
