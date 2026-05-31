"""מאגר תנועות מצטבר ומדודפלק לכל פרויקט (כרטסת הנהלת חשבונות).

רעיון מרכזי
-----------
במקום לפצל ידנית את הכרטסת לחודשים, המשתמש מעלה כל חודש קובץ כרטסת
מצטבר ("עד היום"). כל שורה מקבלת ``row_hash`` ייחודי, והמערכת:
    • מזהה תנועות חדשות (hash שלא קיים) ומוסיפה אותן.
    • מדלגת על כפילויות (hash שכבר קיים).
    • מזהה תנועות שהשתנו (אותו מפתח לוגי, סכום שונה) ומסמנת אזהרה.
    • מסווגת כל תנועה לחודש לפי *תאריך התנועה* ולא לפי מועד ההעלאה.

המאגר נשמר כ-parquet בתיקיית הפרויקט:
    data/projects/<project_id>/_ledger_store.parquet

מצבי יבוא (mode):
    "add_new"       — הוסף רק תנועות חדשות (לפי row_hash).
    "replace_range" — מחק במאגר את כל התנועות בטווח התאריכים של הקובץ,
                       ואז הוסף את כל שורות הקובץ (לתיקון רטרואקטיבי).
    "check_only"    — ניתוח בלבד, ללא שמירה.

הכרטסת היא מקור התנועות. המאזן (balance_store) הוא בקרה בלבד.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# העמודות שנשמרות במאגר: סכמת load_chashbashevet + שדות מאגר.
STORE_META_COLS = ["row_hash", "key_hash", "month", "import_date", "source_file"]


def _store_path(project_id: str) -> Path:
    """נתיב קובץ המאגר של הפרויקט."""
    from pipeline import PROJECTS_ROOT
    return PROJECTS_ROOT / project_id / "_ledger_store.parquet"


def _norm_num(val: float | int | None) -> str:
    """מנרמל מספר לייצוג עקבי לצורך hash (2 ספרות אחרי הנקודה)."""
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _norm_date(val) -> str:
    """מנרמל תאריך ל-ISO (YYYY-MM-DD); ריק אם לא ניתן."""
    ts = pd.to_datetime(val, errors="coerce")
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y-%m-%d")


def compute_row_hash(date, account_num, details: str,
                     debit: float, credit: float) -> str:
    """מחשב hash ייחודי לשורת תנועה (זהות מלאה כולל סכומים).

    שדות: תאריך + מספר חשבון + פרטים + חובה + זכות.
    שתי שורות עם אותו hash נחשבות לאותה תנועה (כפילות).
    """
    parts = [
        _norm_date(date),
        str(account_num if account_num is not None and not pd.isna(account_num) else ""),
        (details or "").strip(),
        _norm_num(debit),
        _norm_num(credit),
    ]
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def compute_key_hash(date, account_num, details: str) -> str:
    """מפתח לוגי של תנועה ללא סכומים (לזיהוי 'תנועה שהשתנתה').

    אם אותו מפתח קיים אך ה-row_hash שונה → הסכום השתנה (עדכון).
    """
    parts = [
        _norm_date(date),
        str(account_num if account_num is not None and not pd.isna(account_num) else ""),
        (details or "").strip(),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def add_hashes(df: pd.DataFrame) -> pd.DataFrame:
    """מוסיף עמודות row_hash, key_hash, month ל-DataFrame של תנועות.

    Args:
        df: פלט load_chashbashevet (עמודות date/account_num/details/debit/credit).

    Returns:
        עותק עם העמודות החדשות.
    """
    df = df.copy()
    if df.empty:
        for c in ("row_hash", "key_hash", "month"):
            if c not in df.columns:
                df[c] = pd.Series(dtype="object")
        return df

    df["row_hash"] = df.apply(
        lambda r: compute_row_hash(
            r.get("date"), r.get("account_num"), r.get("details", ""),
            r.get("debit", 0.0), r.get("credit", 0.0),
        ), axis=1,
    )
    df["key_hash"] = df.apply(
        lambda r: compute_key_hash(
            r.get("date"), r.get("account_num"), r.get("details", ""),
        ), axis=1,
    )
    dt = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = dt.dt.strftime("%m-%Y")
    return df


def load_store(project_id: str) -> pd.DataFrame:
    """טוען את מאגר התנועות של הפרויקט. ריק אם לא קיים."""
    path = _store_path(project_id)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    except Exception as e:
        logger.exception("Failed to load ledger store %s: %s", path, e)
        return pd.DataFrame()


def has_store(project_id: str) -> bool:
    """האם קיים מאגר תנועות מצטבר לפרויקט."""
    return _store_path(project_id).exists()


def save_store(project_id: str, df: pd.DataFrame) -> None:
    """שומר את מאגר התנועות ל-parquet."""
    path = _store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
        logger.info("Saved ledger store (%d rows) to %s", len(df), path)
    except Exception as e:
        logger.exception("Failed to save ledger store %s: %s", path, e)


def _empty_summary() -> dict:
    return {
        "rows_in_file": 0, "new_count": 0, "duplicate_count": 0,
        "updated_count": 0, "store_before": 0, "store_after": 0,
        "date_min": None, "date_max": None, "months": [],
        "debit_sum": 0.0, "credit_sum": 0.0, "amount_sum": 0.0,
        "no_date_count": 0, "no_amount_count": 0,
    }


def analyze(project_id: str, incoming: pd.DataFrame,
            mode: str = "add_new") -> dict:
    """מנתח יבוא מבלי לשמור — מחזיר סיכום לתצוגה מקדימה.

    Args:
        project_id: מזהה הפרויקט.
        incoming: פלט load_chashbashevet של הקובץ שהועלה.
        mode: "add_new" / "replace_range" / "check_only".

    Returns:
        dict עם: rows_in_file, new_count, duplicate_count, updated_count,
        store_before, store_after, date_min, date_max, months, debit_sum,
        credit_sum, amount_sum, no_date_count, no_amount_count.
    """
    summary = _empty_summary()
    if incoming is None or incoming.empty:
        return summary

    inc = add_hashes(incoming)
    summary["rows_in_file"] = len(inc)
    summary["debit_sum"] = float(inc.get("debit", pd.Series(dtype=float)).sum())
    summary["credit_sum"] = float(inc.get("credit", pd.Series(dtype=float)).sum())
    summary["amount_sum"] = float(inc.get("amount", pd.Series(dtype=float)).sum())

    dt = pd.to_datetime(inc["date"], errors="coerce")
    summary["no_date_count"] = int(dt.isna().sum())
    valid_dt = dt.dropna()
    if not valid_dt.empty:
        summary["date_min"] = valid_dt.min()
        summary["date_max"] = valid_dt.max()
    summary["months"] = sorted(inc["month"].dropna().unique().tolist())

    amt = pd.to_numeric(inc.get("amount", pd.Series(dtype=float)), errors="coerce").fillna(0)
    summary["no_amount_count"] = int((amt == 0).sum())

    store = load_store(project_id)
    summary["store_before"] = len(store)
    existing_row = set(store["row_hash"]) if not store.empty and "row_hash" in store else set()
    existing_key = set(store["key_hash"]) if not store.empty and "key_hash" in store else set()

    if mode == "replace_range" and not store.empty and summary["date_min"] is not None:
        # בטווח התאריכים של הקובץ — כל מה שבמאגר יוחלף
        store_dt = pd.to_datetime(store["date"], errors="coerce")
        in_range = (store_dt >= summary["date_min"]) & (store_dt <= summary["date_max"])
        removed = int(in_range.sum())
        kept_rows = set(store.loc[~in_range, "row_hash"])
        kept_keys = set(store.loc[~in_range, "key_hash"])
        summary["new_count"] = len(inc)  # כל הקובץ ייכנס
        summary["duplicate_count"] = 0
        summary["updated_count"] = removed
        summary["store_after"] = len(kept_rows) + len(inc)
    else:
        is_dup = inc["row_hash"].isin(existing_row)
        is_update = (~is_dup) & inc["key_hash"].isin(existing_key)
        is_new = (~is_dup) & (~inc["key_hash"].isin(existing_key))
        summary["duplicate_count"] = int(is_dup.sum())
        summary["updated_count"] = int(is_update.sum())
        summary["new_count"] = int(is_new.sum())
        # add_new מוסיף חדש + עדכונים (row_hash שונה) ; כפילויות מדלגות
        added = int((~is_dup).sum())
        summary["store_after"] = len(existing_row) + added

    return summary


def apply_import(project_id: str, incoming: pd.DataFrame,
                 mode: str = "add_new", source_file: str = "") -> dict:
    """מבצע את היבוא בפועל ושומר את המאגר. מחזיר את אותו סיכום כמו analyze.

    mode == "check_only" אינו שומר דבר.
    """
    summary = analyze(project_id, incoming, mode)
    if mode == "check_only" or incoming is None or incoming.empty:
        return summary

    from datetime import datetime
    inc = add_hashes(incoming)
    inc["import_date"] = datetime.now().strftime("%Y-%m-%d")
    inc["source_file"] = source_file

    store = load_store(project_id)

    if store.empty:
        merged = inc
    elif mode == "replace_range":
        dmin, dmax = summary["date_min"], summary["date_max"]
        if dmin is not None:
            store_dt = pd.to_datetime(store["date"], errors="coerce")
            in_range = (store_dt >= dmin) & (store_dt <= dmax)
            kept = store.loc[~in_range]
            merged = pd.concat([kept, inc], ignore_index=True, sort=False)
        else:
            merged = pd.concat([store, inc], ignore_index=True, sort=False)
    else:  # add_new — הוסף רק row_hash שלא קיים
        existing = set(store["row_hash"]) if "row_hash" in store else set()
        fresh = inc[~inc["row_hash"].isin(existing)]
        merged = pd.concat([store, fresh], ignore_index=True, sort=False)

    # הסרת כפילויות בטוחה (אם נכנס אותו row_hash פעמיים)
    if "row_hash" in merged.columns:
        merged = merged.drop_duplicates(subset=["row_hash"], keep="last")

    merged = merged.reset_index(drop=True)
    save_store(project_id, merged)
    summary["store_after"] = len(merged)
    return summary


def delete_store(project_id: str) -> bool:
    """מוחק את מאגר התנועות של הפרויקט. מחזיר True אם נמחק."""
    path = _store_path(project_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception as e:
            logger.warning("Failed to delete ledger store: %s", e)
    return False
