"""מאגר הזנה ידנית בסגנון אקסל — סולר ושעות עבודה.

רעיון מרכזי
-----------
במקום להעלות קובץ אקסל ולבנות פורמט חדש בכל פעם, המשתמש מדביק נתונים
ישירות לטבלה במערכת (st.data_editor). כל שורה מקבלת ``row_hash`` ייחודי
והמערכת:
    • מזהה שורות חדשות (hash שלא קיים) ומוסיפה אותן.
    • מדלגת על כפילויות (hash שכבר קיים).
    • מזהה שורות שהשתנו (אותו מפתח לוגי, ערכים שונים) למצב "עדכן".
    • מסווגת כל שורה לחודש לפי *תאריך השורה* ולא לפי מועד ההזנה.
    • מחשבת אוטומטית סכום כולל (כמות × מחיר) וסה"כ שעות אם חסרים.

המאגר נשמר כ-parquet בתיקיית הפרויקט:
    data/projects/<project_id>/_manual_solar_store.parquet
    data/projects/<project_id>/_manual_hours_store.parquet

מצבי שמירה (mode):
    "add_new"         — הוסף רק שורות חדשות (לפי row_hash).
    "update_existing" — עדכן שורות עם אותו מפתח לוגי (key_hash) + הוסף חדשות.
    "replace_month"   — מחק במאגר את כל השורות בחודש הנבחר, ואז הוסף את הקלט.
    "check_only"      — ניתוח בלבד, ללא שמירה.

הנתונים הידניים זורמים ל-master.parquet (pipeline.aggregate_manual_*) ולכן
משפיעים על כל הטאבים, ה-KPIs והגרפים בדף הפרויקט.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ── סוגי דלק לבחירה בדוח סולר ──────────────────────────────────
FUEL_TYPES = ["סולר צמ\"ה", "סולר רכבים", "בנזין", "חשמל"]


# ── הגדרת העמודות לכל סוג דוח ───────────────────────────────────
# כל עמודה: (key, label, kind)  kind ∈ date/int/float/text/select
KINDS: dict[str, dict] = {
    "solar": {
        "label": "סולר",
        "store_file": "_manual_solar_store.parquet",
        "columns": [
            ("date", "תאריך", "date"),
            ("license_num", "מספר כלי / רכב", "int"),
            ("tool_name", "שם כלי / רכב", "text"),
            ("fuel_type", "סוג דלק", "select"),
            ("supplier", "ספק", "text"),
            ("invoice_num", "מספר חשבונית / אסמכתא", "text"),
            ("liters", "כמות ליטרים", "float"),
            ("price_per_liter", "מחיר לליטר", "float"),
            ("amount", "סכום כולל", "float"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "liters"],
        # מפתח כפילות מלא (כולל סכומים)
        "hash_fields": ["date", "license_num", "supplier", "invoice_num",
                        "liters", "amount"],
        # מפתח לוגי (ללא סכומים) — לזיהוי "שורה שהשתנתה"
        "key_fields": ["date", "license_num", "supplier", "invoice_num"],
        "select_options": {"fuel_type": FUEL_TYPES},
    },
    "hours": {
        "label": "שעות עבודה",
        "store_file": "_manual_hours_store.parquet",
        "columns": [
            ("date", "תאריך", "date"),
            ("employee_name", "שם עובד", "text"),
            ("employee_id", "ת.ז / מספר עובד", "text"),
            ("site", "אתר / מקום עבודה", "text"),
            ("work_type", "סוג עבודה", "text"),
            ("regular_hours", "שעות רגילות 100%", "float"),
            ("ot_125", "שעות נוספות 125%", "float"),
            ("ot_150", "שעות נוספות 150%", "float"),
            ("ot_175", "שעות נוספות 175%", "float"),
            ("ot_200", "שעות נוספות 200%", "float"),
            ("total_hours", "סה\"כ שעות", "float"),
            ("cost_per_hour", "עלות לשעה", "float"),
            ("total_cost", "סה\"כ עלות", "float"),
            ("notes", "הערות", "text"),
        ],
        "required": ["date", "employee_name"],
        "hash_fields": ["date", "employee_name", "site", "regular_hours",
                        "ot_125", "ot_150", "ot_175", "ot_200", "total_hours"],
        "key_fields": ["date", "employee_name", "site", "work_type"],
        "select_options": {},
    },
}

# עמודות שעות נוספות לחישוב סה"כ אוטומטי
_OT_COLS = ["regular_hours", "ot_125", "ot_150", "ot_175", "ot_200"]

# עמודות שירות (לא חלק מהקלט אך נשמרות במאגר)
STORE_META_COLS = ["row_hash", "key_hash", "month", "import_date", "source_file"]


# ── עזרי נורמליזציה ────────────────────────────────────────────
def column_keys(kind: str) -> list[str]:
    """מחזיר את רשימת מפתחות העמודות (באנגלית) לסוג דוח."""
    return [c[0] for c in KINDS[kind]["columns"]]


def column_labels(kind: str) -> dict[str, str]:
    """מיפוי key→label עברית לסוג דוח."""
    return {c[0]: c[1] for c in KINDS[kind]["columns"]}


def column_kind(kind: str, key: str) -> str:
    """מחזיר את טיפוס העמודה (date/int/float/text/select)."""
    for c in KINDS[kind]["columns"]:
        if c[0] == key:
            return c[2]
    return "text"


def _norm_num(val) -> str:
    """מנרמל מספר לייצוג עקבי ל-hash (2 ספרות אחרי הנקודה)."""
    try:
        if val is None or pd.isna(val):
            return "0.00"
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _norm_date(val) -> str:
    """מנרמל תאריך ל-ISO (YYYY-MM-DD); ריק אם לא ניתן."""
    ts = pd.to_datetime(val, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y-%m-%d")


def _norm_text(val) -> str:
    """מנרמל טקסט: strip, NaN→''."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s


def _hash_part(kind: str, field: str, value) -> str:
    """מחזיר ייצוג מנורמל של שדה בודד לצורך hash."""
    ckind = column_kind(kind, field)
    if ckind == "date":
        return _norm_date(value)
    if ckind in ("int", "float"):
        return _norm_num(value)
    return _norm_text(value)


def compute_row_hash(kind: str, row: dict) -> str:
    """מחשב hash ייחודי לשורה (זהות מלאה — כפילות אם זהה)."""
    parts = [_hash_part(kind, f, row.get(f)) for f in KINDS[kind]["hash_fields"]]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def compute_key_hash(kind: str, row: dict) -> str:
    """מחשב מפתח לוגי (ללא ערכים מספריים) — לזיהוי שורה שהשתנתה."""
    parts = [_hash_part(kind, f, row.get(f)) for f in KINDS[kind]["key_fields"]]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


# ── חישובים אוטומטיים ──────────────────────────────────────────
def _autocompute_row(kind: str, row: dict) -> dict:
    """ממלא ערכים חסרים: סכום כולל (סולר), סה"כ שעות/עלות (שעות)."""
    out = dict(row)
    if kind == "solar":
        liters = _to_float(out.get("liters"))
        price = _to_float(out.get("price_per_liter"))
        amount = _to_float(out.get("amount"))
        if (amount is None or amount == 0) and liters and price:
            out["amount"] = round(liters * price, 2)
    elif kind == "hours":
        total = _to_float(out.get("total_hours"))
        if total is None or total == 0:
            parts = [_to_float(out.get(c)) or 0.0 for c in _OT_COLS]
            s = sum(parts)
            if s > 0:
                out["total_hours"] = round(s, 2)
                total = out["total_hours"]
        cost_ph = _to_float(out.get("cost_per_hour"))
        total_cost = _to_float(out.get("total_cost"))
        if (total_cost is None or total_cost == 0) and total and cost_ph:
            out["total_cost"] = round(total * cost_ph, 2)
    return out


def _to_float(val) -> float | None:
    """המרה בטוחה ל-float; None אם ריק/לא מספרי."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(val)
    except (TypeError, ValueError):
        if isinstance(val, str):
            cleaned = val.replace(",", "").replace("₪", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


def _coerce_types(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    """ממיר את עמודות ה-DataFrame לטיפוסים הנכונים לפי הגדרת ה-kind."""
    df = df.copy()
    for key, _label, ckind in KINDS[kind]["columns"]:
        if key not in df.columns:
            df[key] = pd.NA
            continue
        if ckind == "date":
            df[key] = pd.to_datetime(df[key], errors="coerce", dayfirst=True)
        elif ckind == "int":
            df[key] = pd.to_numeric(df[key], errors="coerce").astype("Int64")
        elif ckind == "float":
            df[key] = pd.to_numeric(df[key], errors="coerce")
        else:  # text / select
            df[key] = df[key].apply(_norm_text)
    return df


def empty_frame(kind: str) -> pd.DataFrame:
    """DataFrame ריק עם כל עמודות הקלט (לזריעת ה-editor)."""
    cols = column_keys(kind)
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    return _coerce_types(kind, df)


def prepare_incoming(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    """מנקה קלט גולמי מה-editor: מסיר שורות ריקות, ממיר טיפוסים,

    מחשב ערכים אוטומטיים, ומוסיף row_hash/key_hash/month.
    שורות ללא תאריך תקין או ללא שדה חובה נשמרות (יסומנו כשגיאה ב-analyze).
    """
    if df is None or df.empty:
        return empty_frame(kind)
    df = df.copy()
    # שמור רק עמודות מוכרות
    keep = [c for c in column_keys(kind) if c in df.columns]
    df = df[keep]
    df = _coerce_types(kind, df)

    # הסרת שורות ריקות לחלוטין (כל העמודות NA/ריק)
    def _is_blank_row(r) -> bool:
        for v in r:
            if v is None:
                continue
            try:
                if pd.isna(v):
                    continue
            except (TypeError, ValueError):
                pass
            if isinstance(v, str) and not v.strip():
                continue
            return False
        return True

    df = df[~df.apply(_is_blank_row, axis=1)].reset_index(drop=True)
    if df.empty:
        return empty_frame(kind)

    # חישובים אוטומטיים שורה-שורה
    records = [_autocompute_row(kind, r._asdict() if hasattr(r, "_asdict") else dict(zip(df.columns, r)))
               for r in df.itertuples(index=False)]
    df = pd.DataFrame(records)
    df = _coerce_types(kind, df)

    # hashes + month
    df["row_hash"] = df.apply(lambda r: compute_row_hash(kind, r.to_dict()), axis=1)
    df["key_hash"] = df.apply(lambda r: compute_key_hash(kind, r.to_dict()), axis=1)
    dt = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = dt.dt.strftime("%m-%Y")
    return df.reset_index(drop=True)


# ── נתיב + I/O ─────────────────────────────────────────────────
def _store_path(project_id: str, kind: str) -> Path:
    """נתיב קובץ המאגר לפרויקט + סוג דוח."""
    from pipeline import PROJECTS_ROOT
    return PROJECTS_ROOT / project_id / KINDS[kind]["store_file"]


def has_store(project_id: str, kind: str) -> bool:
    """האם קיים מאגר ידני מסוג זה לפרויקט."""
    return _store_path(project_id, kind).exists()


def load_store(project_id: str, kind: str) -> pd.DataFrame:
    """טוען את המאגר הידני. ריק אם לא קיים."""
    path = _store_path(project_id, kind)
    if not path.exists():
        return empty_frame(kind)
    try:
        df = pd.read_parquet(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    except Exception as e:
        logger.exception("Failed to load manual %s store %s: %s", kind, path, e)
        return empty_frame(kind)


def save_store(project_id: str, kind: str, df: pd.DataFrame) -> None:
    """שומר את המאגר ל-parquet."""
    path = _store_path(project_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
        logger.info("Saved manual %s store (%d rows) to %s", kind, len(df), path)
    except Exception as e:
        logger.exception("Failed to save manual %s store %s: %s", kind, path, e)


def delete_store(project_id: str, kind: str) -> bool:
    """מוחק את המאגר. מחזיר True אם נמחק."""
    path = _store_path(project_id, kind)
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception as e:
            logger.warning("Failed to delete manual %s store: %s", kind, e)
    return False


# ── ניתוח / יבוא ───────────────────────────────────────────────
def validate_incoming(kind: str, prepared: pd.DataFrame) -> pd.Series:
    """מחזיר Series בוליאני: True לשורות תקינות (כל שדות החובה + תאריך).

    שורה תקינה = יש לה תאריך תקין וכל שדות החובה מלאים.
    """
    if prepared.empty:
        return pd.Series([], dtype=bool)
    required = KINDS[kind]["required"]
    ok = pd.Series(True, index=prepared.index)
    # תאריך תקין (month לא NaN)
    ok &= prepared["month"].notna() & (prepared["month"].astype(str) != "")
    for field in required:
        if field in ("date",):
            continue
        col = prepared[field] if field in prepared.columns else pd.Series(pd.NA, index=prepared.index)
        ckind = column_kind(kind, field)
        if ckind in ("int", "float"):
            ok &= pd.to_numeric(col, errors="coerce").notna()
        else:
            ok &= col.apply(lambda v: bool(_norm_text(v)))
    return ok


def _empty_summary() -> dict:
    return {
        "rows_in_file": 0, "valid_count": 0, "error_count": 0,
        "new_count": 0, "duplicate_count": 0, "updated_count": 0,
        "store_before": 0, "store_after": 0,
        "date_min": None, "date_max": None, "months": [],
        "amount_sum": 0.0, "liters_sum": 0.0, "hours_sum": 0.0,
        # תאימות ל-db.log_import
        "new_count_": 0, "no_date_count": 0, "no_amount_count": 0,
        "debit_sum": 0.0, "credit_sum": 0.0,
    }


def analyze(project_id: str, kind: str, incoming: pd.DataFrame,
            mode: str = "add_new", target_month: str | None = None) -> dict:
    """מנתח יבוא מבלי לשמור — מחזיר סיכום לתצוגה מקדימה.

    Args:
        project_id: מזהה הפרויקט.
        kind: "solar" / "hours".
        incoming: ה-DataFrame הגולמי מה-editor (לפני prepare).
        mode: add_new / update_existing / replace_month / check_only.
        target_month: חודש (MM-YYYY) לשימוש במצב replace_month.

    Returns:
        dict עם ספירות, סכומים, חודשים מושפעים ועוד.
    """
    summary = _empty_summary()
    prepared = prepare_incoming(kind, incoming)
    if prepared.empty:
        return summary

    summary["rows_in_file"] = len(prepared)
    valid_mask = validate_incoming(kind, prepared)
    summary["valid_count"] = int(valid_mask.sum())
    summary["error_count"] = int((~valid_mask).sum())
    summary["no_date_count"] = int((prepared["month"].isna() |
                                    (prepared["month"].astype(str) == "")).sum())

    valid = prepared[valid_mask]
    dt = pd.to_datetime(valid["date"], errors="coerce").dropna()
    if not dt.empty:
        summary["date_min"] = dt.min()
        summary["date_max"] = dt.max()
    summary["months"] = sorted(valid["month"].dropna().unique().tolist())

    if "amount" in valid.columns:
        summary["amount_sum"] = float(pd.to_numeric(valid["amount"], errors="coerce").fillna(0).sum())
    if "liters" in valid.columns:
        summary["liters_sum"] = float(pd.to_numeric(valid["liters"], errors="coerce").fillna(0).sum())
    if "total_hours" in valid.columns:
        summary["hours_sum"] = float(pd.to_numeric(valid["total_hours"], errors="coerce").fillna(0).sum())
    if "total_cost" in valid.columns:
        summary["amount_sum"] = float(pd.to_numeric(valid["total_cost"], errors="coerce").fillna(0).sum())

    store = load_store(project_id, kind)
    has_rows = not store.empty and "row_hash" in store.columns
    summary["store_before"] = int(len(store)) if has_rows else 0
    existing_row = set(store["row_hash"]) if has_rows else set()
    existing_key = set(store["key_hash"]) if (has_rows and "key_hash" in store.columns) else set()

    if mode == "replace_month":
        months = set(valid["month"].dropna().unique())
        if target_month:
            months = {target_month}
        kept = 0
        if has_rows and "month" in store.columns:
            kept = int((~store["month"].isin(months)).sum())
        summary["new_count"] = summary["valid_count"]
        summary["duplicate_count"] = 0
        summary["updated_count"] = (summary["store_before"] - kept) if has_rows else 0
        summary["store_after"] = kept + summary["valid_count"]
    else:
        vh = valid["row_hash"]
        vk = valid["key_hash"]
        is_dup = vh.isin(existing_row)
        is_update = (~is_dup) & vk.isin(existing_key)
        is_new = (~is_dup) & (~vk.isin(existing_key))
        summary["duplicate_count"] = int(is_dup.sum())
        summary["updated_count"] = int(is_update.sum())
        summary["new_count"] = int(is_new.sum())
        if mode == "update_existing":
            # מעדכן קיימים (key) + מוסיף חדשים; כפילויות מדלגות
            summary["store_after"] = summary["store_before"] + summary["new_count"]
        else:  # add_new
            summary["store_after"] = summary["store_before"] + int((~is_dup).sum())
    return summary


def apply_import(project_id: str, kind: str, incoming: pd.DataFrame,
                 mode: str = "add_new", source_file: str = "",
                 target_month: str | None = None) -> dict:
    """מבצע את היבוא בפועל ושומר את המאגר. מחזיר סיכום כמו analyze.

    mode == "check_only" אינו שומר דבר. רק שורות תקינות נשמרות.
    """
    summary = analyze(project_id, kind, incoming, mode, target_month)
    if mode == "check_only":
        return summary

    prepared = prepare_incoming(kind, incoming)
    if prepared.empty:
        return summary
    valid_mask = validate_incoming(kind, prepared)
    valid = prepared[valid_mask].copy()
    if valid.empty:
        return summary

    valid["import_date"] = datetime.now().strftime("%Y-%m-%d")
    valid["source_file"] = source_file or "הזנה ידנית"

    store = load_store(project_id, kind)
    store_has = not store.empty and "row_hash" in store.columns

    if not store_has:
        merged = valid
    elif mode == "replace_month":
        months = set(valid["month"].dropna().unique())
        if target_month:
            months = {target_month}
        kept = store[~store["month"].isin(months)] if "month" in store.columns else store
        merged = pd.concat([kept, valid], ignore_index=True, sort=False)
    elif mode == "update_existing":
        # הסר מהמאגר שורות עם key_hash שמופיע בקלט, ואז הוסף את כל הקלט התקין
        incoming_keys = set(valid["key_hash"])
        kept = store[~store["key_hash"].isin(incoming_keys)] if "key_hash" in store.columns else store
        merged = pd.concat([kept, valid], ignore_index=True, sort=False)
    else:  # add_new — הוסף רק row_hash שלא קיים
        existing = set(store["row_hash"])
        fresh = valid[~valid["row_hash"].isin(existing)]
        merged = pd.concat([store, fresh], ignore_index=True, sort=False)

    if "row_hash" in merged.columns:
        merged = merged.drop_duplicates(subset=["row_hash"], keep="last")
    merged = merged.reset_index(drop=True)
    save_store(project_id, kind, merged)
    summary["store_after"] = len(merged)
    return summary
