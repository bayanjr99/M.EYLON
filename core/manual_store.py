"""מאגר הזנה ידנית בסגנון אקסל — סולר ושעות עבודה.

רעיון מרכזי
-----------
במקום להעלות קובץ אקסל ולבנות פורמט חדש בכל פעם, המשתמש מדביק נתונים
ישירות (TSV מאקסל). המערכת מזהה את העמודות אוטומטית (או נותנת למפות אותן
ידנית), בודקת שגיאות שורה-שורה, ושומרת רק שורות תקינות:
    • מזהה שורות חדשות (row_hash שלא קיים) ומוסיפה אותן.
    • מדלגת על כפילויות (row_hash שכבר קיים).
    • מזהה שורות שהשתנו (אותו key_hash, ערכים שונים) למצב "עדכן".
    • מסווגת כל שורה לחודש לפי *תאריך השורה* — אין צורך למלא חודש ידנית.
    • מחשבת אוטומטית סכום/מחיר-לליטר/סה"כ שעות אם חסרים.

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

from utils import hebrew

logger = logging.getLogger(__name__)


# ── סוגי דלק לבחירה בדוח סולר ──────────────────────────────────
FUEL_TYPES = ["סולר צמ\"ה", "סולר רכבים", "בנזין", "חשמל"]
FUEL_DEFAULT = "לא סווג"


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
        # תאריך חובה + לפחות אחד מ-(ליטרים / סכום)
        "required_all": ["date"],
        "required_any": [["liters", "amount"]],
        # חוסר באלה = אזהרה בלבד (לא חוסם שמירה)
        "warn_any": [["tool_name", "license_num"], ["supplier", "invoice_num"]],
        # מפתח כפילות מלא (כולל סכומים)
        "hash_fields": ["date", "license_num", "supplier", "invoice_num",
                        "liters", "amount"],
        # מפתח לוגי (ללא סכומים) — לזיהוי "שורה שהשתנתה"
        "key_fields": ["date", "license_num", "supplier", "invoice_num"],
        "select_options": {"fuel_type": FUEL_TYPES + [FUEL_DEFAULT]},
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
        "required_all": ["date", "employee_name"],
        "required_any": [["total_hours", "regular_hours", "ot_125",
                          "ot_150", "ot_175", "ot_200"]],
        "warn_any": [["site"]],
        "hash_fields": ["date", "employee_name", "site", "regular_hours",
                        "ot_125", "ot_150", "ot_175", "ot_200", "total_hours"],
        "key_fields": ["date", "employee_name", "site", "work_type"],
        "select_options": {},
    },
}

# עמודות שעות (לחישוב סה"כ אוטומטי)
_OT_COLS = ["regular_hours", "ot_125", "ot_150", "ot_175", "ot_200"]

# עמודות שירות (לא חלק מהקלט אך נשמרות במאגר)
STORE_META_COLS = ["row_hash", "key_hash", "month", "import_date", "source_file"]


# ── וריאציות שמות עמודות לזיהוי אוטומטי בעת הדבקה ──────────────
# המפתח = שדה במערכת, הערך = רשימת וריאציות אפשריות בכותרת מאקסל.
COLUMN_SYNONYMS: dict[str, dict[str, list[str]]] = {
    "solar": {
        "date": ["תאריך", "תאריך פעולה", "תאריך תדלוק", "ת. אסמכתא",
                 "תאריך אסמכתא", "יום", "date"],
        "license_num": ["מספר כלי", "מספר רכב", "מס כלי", "מס רכב", "מס' כלי",
                        "מס' רכב", "כלי", "רכב", "מספר רישוי", "רישוי",
                        "license", "license_num"],
        "tool_name": ["שם כלי", "שם רכב", "שם הכלי", "תיאור כלי", "כלי / רכב",
                      "שם כלי / רכב", "תיאור", "tool", "tool_name"],
        "fuel_type": ["סוג דלק", "דלק", "סוג", "fuel", "fuel_type"],
        "supplier": ["ספק", "תחנה", "שם ספק", "תחנת דלק", "supplier"],
        "invoice_num": ["מספר חשבונית", "חשבונית", "אסמכתא", "מסמך",
                        "מס חשבונית", "מס' חשבונית", "חשבונית / אסמכתא",
                        "invoice", "reference", "invoice_num"],
        "liters": ["כמות ליטרים", "ליטרים", "כמות", "כמות דלק", "ליטר",
                   "liters", "litre", "litres"],
        "price_per_liter": ["מחיר לליטר", "מחיר ליטר", "מחיר יחידה", "מחיר",
                            "price", "price_per_liter"],
        "amount": ["סכום כולל", "סכום", "עלות", "חובה", "סהכ", "סה\"כ",
                   "סך הכל", "סך הכול", "total", "amount"],
        "notes": ["הערות", "הערה", "פירוט", "notes"],
    },
    "hours": {
        "date": ["תאריך", "תאריך עבודה", "יום", "date"],
        "employee_name": ["שם עובד", "שם העובד", "שם", "עובד", "employee",
                          "name", "employee_name"],
        "employee_id": ["ת.ז", "תז", "ת\"ז", "מספר עובד", "מס עובד",
                        "מס' עובד", "תעודת זהות", "id", "employee_id"],
        "site": ["אתר", "מקום עבודה", "אתר עבודה", "מיקום", "site"],
        "work_type": ["סוג עבודה", "תפקיד", "עבודה", "work", "work_type"],
        "regular_hours": ["שעות רגילות 100%", "שעות רגילות", "רגילות",
                          "שעות 100%", "100%", "שעות רגילה", "regular"],
        "ot_125": ["שעות נוספות 125%", "נוספות 125%", "125%", "125", "ot 125"],
        "ot_150": ["שעות נוספות 150%", "נוספות 150%", "150%", "150", "ot 150"],
        "ot_175": ["שעות נוספות 175%", "נוספות 175%", "175%", "175", "ot 175"],
        "ot_200": ["שעות נוספות 200%", "נוספות 200%", "200%", "200", "ot 200"],
        "total_hours": ["סה\"כ שעות", "סהכ שעות", "סך שעות", "שעות",
                        "total hours", "total_hours"],
        "cost_per_hour": ["עלות לשעה", "מחיר לשעה", "תעריף", "תעריף לשעה",
                          "cost", "cost_per_hour"],
        "total_cost": ["סה\"כ עלות", "סהכ עלות", "עלות כוללת", "עלות כולל",
                       "total cost", "total_cost"],
        "notes": ["הערות", "הערה", "notes"],
    },
}


# ── עזרי עמודות ────────────────────────────────────────────────
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


# ── נורמליזציה ─────────────────────────────────────────────────
def _to_float(val) -> float | None:
    """המרה בטוחה ל-float; None אם ריק/לא מספרי. מנקה פסיקים ו-₪."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    cleaned = (s.replace(",", "").replace("₪", "").replace("%", "")
               .replace("‏", "").replace("‎", "").strip())
    if cleaned in ("", "-", "nan", "nat", "none"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_date_series(s: pd.Series) -> pd.Series:
    """ממיר Series לתאריכים — תומך ב-31/05/2026 וגם 31.05.2026 / 31-05-2026."""
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if dt.isna().any():
        try:
            txt = s.astype(str)
        except Exception:
            return dt
        mask = dt.isna() & txt.str.strip().ne("") & txt.str.lower().ne("nan")
        if mask.any():
            alt = (txt[mask].str.replace(".", "/", regex=False)
                   .str.replace("-", "/", regex=False))
            dt.loc[mask] = pd.to_datetime(alt, errors="coerce", dayfirst=True)
    return dt


def _norm_num(val) -> str:
    """מנרמל מספר לייצוג עקבי ל-hash (2 ספרות אחרי הנקודה)."""
    f = _to_float(val)
    return f"{f:.2f}" if f is not None else "0.00"


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


# ── זיהוי עמודות אוטומטי + מיפוי ───────────────────────────────
def _match_field(kind: str, header_cell: str) -> tuple[str | None, int]:
    """מחזיר (field, score) להתאמה הטובה ביותר של כותרת לשדה במערכת.

    score = אורך הווריאציה שהותאמה (ארוך יותר = ספציפי יותר). 0 אם אין.
    """
    norm_h = hebrew.normalize(str(header_cell or ""))
    if not norm_h:
        return None, 0
    best_field, best_score = None, 0
    for field, syns in COLUMN_SYNONYMS[kind].items():
        for syn in syns:
            ns = hebrew.normalize(syn)
            if not ns:
                continue
            if ns == norm_h or ns in norm_h or norm_h in ns:
                score = len(ns)
                if score > best_score:
                    best_field, best_score = field, score
    return best_field, best_score


def detect_header(kind: str, raw: pd.DataFrame) -> bool:
    """האם השורה הראשונה היא כותרת? (התאמה של ≥2 תאים לשמות שדות)."""
    if raw.empty:
        return False
    first = raw.iloc[0].tolist()
    matches = sum(1 for cell in first if _match_field(kind, str(cell))[0])
    # ובנוסף: התא הראשון אינו תאריך תקין (כותרת אמיתית)
    looks_like_data_date = not pd.isna(
        pd.to_datetime(str(first[0]) if first else "", errors="coerce",
                       dayfirst=True))
    return matches >= 2 and not looks_like_data_date


def guess_mapping(kind: str, header: list[str] | None) -> dict[str, int | None]:
    """מנחש מיפוי field→מספר עמודת מקור לפי שמות הכותרות.

    אם אין כותרות (header=None) → מיפוי לפי סדר עמודות ברירת המחדל.
    מבטיח שכל עמודת מקור משויכת לכל היותר לשדה אחד (greedy לפי score).
    """
    keys = column_keys(kind)
    if not header:
        return {k: (i if i < 999 else None) for i, k in enumerate(keys)}

    # אסוף מועמדים (field, col_idx, score)
    cands: list[tuple[str, int, int]] = []
    for idx, cell in enumerate(header):
        field, score = _match_field(kind, str(cell))
        if field and score > 0:
            cands.append((field, idx, score))
    cands.sort(key=lambda t: t[2], reverse=True)

    mapping: dict[str, int | None] = {k: None for k in keys}
    used_cols: set[int] = set()
    for field, idx, _score in cands:
        if mapping.get(field) is None and idx not in used_cols:
            mapping[field] = idx
            used_cols.add(idx)
    return mapping


def apply_mapping(kind: str, raw: pd.DataFrame,
                  mapping: dict[str, int | None],
                  has_header: bool) -> pd.DataFrame:
    """בונה DataFrame בעמודות המערכת מתוך טבלה גולמית (מיקומית) + מיפוי."""
    body = raw.iloc[1:] if has_header and len(raw) > 1 else raw
    body = body.reset_index(drop=True)
    out = {}
    ncols = body.shape[1]
    for field in column_keys(kind):
        idx = mapping.get(field)
        if idx is not None and 0 <= idx < ncols:
            out[field] = body.iloc[:, idx].values
        else:
            out[field] = [None] * len(body)
    return pd.DataFrame(out)


# ── חישובים אוטומטיים ──────────────────────────────────────────
def _autocompute_row(kind: str, row: dict) -> dict:
    """ממלא ערכים חסרים: סכום/מחיר (סולר), סה"כ שעות/עלות (שעות)."""
    out = dict(row)
    if kind == "solar":
        liters = _to_float(out.get("liters"))
        price = _to_float(out.get("price_per_liter"))
        amount = _to_float(out.get("amount"))
        if (amount is None or amount == 0) and liters and price:
            out["amount"] = round(liters * price, 2)
        elif (price is None or price == 0) and amount and liters:
            out["price_per_liter"] = round(amount / liters, 4)
        # ברירת מחדל לסוג דלק
        if not _norm_text(out.get("fuel_type")):
            out["fuel_type"] = FUEL_DEFAULT
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


def _coerce_types(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    """ממיר את עמודות ה-DataFrame לטיפוסים הנכונים לפי הגדרת ה-kind."""
    df = df.copy()
    for key, _label, ckind in KINDS[kind]["columns"]:
        if key not in df.columns:
            df[key] = pd.NA
            continue
        if ckind == "date":
            df[key] = _to_date_series(df[key])
        elif ckind == "int":
            df[key] = df[key].apply(_to_float)
            df[key] = pd.to_numeric(df[key], errors="coerce").astype("Int64")
        elif ckind == "float":
            df[key] = df[key].apply(_to_float)
            df[key] = pd.to_numeric(df[key], errors="coerce")
        else:  # text / select
            df[key] = df[key].apply(_norm_text)
    return df


def empty_frame(kind: str) -> pd.DataFrame:
    """DataFrame ריק עם כל עמודות הקלט (לזריעת ה-editor)."""
    cols = column_keys(kind)
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    return _coerce_types(kind, df)


def _is_blank_row(values) -> bool:
    """True אם כל התאים בשורה ריקים/NA."""
    for v in values:
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


def prepare_incoming(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    """מנקה קלט: מסיר שורות ריקות, ממיר טיפוסים, מחשב אוטומטית,

    ומוסיף row_hash/key_hash/month. שורות לא תקינות נשמרות לצורך אבחון.
    """
    if df is None or df.empty:
        return empty_frame(kind)
    df = df.copy()
    keep = [c for c in column_keys(kind) if c in df.columns]
    df = df[keep]
    df = _coerce_types(kind, df)

    # הסר שורות ריקות לחלוטין
    df = df[~df.apply(lambda r: _is_blank_row(r.tolist()), axis=1)].reset_index(drop=True)
    if df.empty:
        return empty_frame(kind)

    # חישובים אוטומטיים שורה-שורה
    records = [_autocompute_row(kind, dict(zip(df.columns, r)))
               for r in df.itertuples(index=False)]
    df = pd.DataFrame(records)
    df = _coerce_types(kind, df)

    df["row_hash"] = df.apply(lambda r: compute_row_hash(kind, r.to_dict()), axis=1)
    df["key_hash"] = df.apply(lambda r: compute_key_hash(kind, r.to_dict()), axis=1)
    dt = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = dt.dt.strftime("%m-%Y")
    return df.reset_index(drop=True)


# ── נתיב + I/O ─────────────────────────────────────────────────
def _store_path(project_id: str, kind: str) -> Path:
    """נתיב קובץ המאגר (parquet קנוני) לפרויקט + סוג דוח.

    מאוחסן תחת data/manual/<project_id>/ — תיקייה *עוקבת-git* (לא מוחרגת),
    כך שהנתונים נשמרים קבוע ומסונכרנים לענן ב-push.
    """
    from pipeline import MANUAL_ROOT
    return MANUAL_ROOT / project_id / KINDS[kind]["store_file"]


def _xlsx_path(project_id: str, kind: str) -> Path:
    """נתיב מראָה ה-xlsx הקריאה (לפתיחה/גיבוי ידני)."""
    from pipeline import MANUAL_ROOT
    name = "fuel_manual.xlsx" if kind == "solar" else "hours_manual.xlsx"
    return MANUAL_ROOT / project_id / name


def _legacy_store_path(project_id: str, kind: str) -> Path:
    """המיקום הישן (מוחרג-git) — לצורך מיגרציה חד-פעמית."""
    from pipeline import PROJECTS_ROOT
    return PROJECTS_ROOT / project_id / KINDS[kind]["store_file"]


def _migrate_legacy(project_id: str, kind: str) -> None:
    """מעביר מאגר מהמיקום הישן (data/projects) לחדש (data/manual) פעם אחת."""
    new = _store_path(project_id, kind)
    if new.exists():
        return
    old = _legacy_store_path(project_id, kind)
    if not old.exists():
        return
    try:
        import shutil
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, new)
        logger.info("Migrated manual %s store: %s -> %s", kind, old, new)
    except Exception as e:
        logger.warning("Legacy migration failed for %s/%s: %s", project_id, kind, e)


def has_store(project_id: str, kind: str) -> bool:
    """האם קיים מאגר ידני מסוג זה לפרויקט."""
    _migrate_legacy(project_id, kind)
    return _store_path(project_id, kind).exists()


def load_store(project_id: str, kind: str) -> pd.DataFrame:
    """טוען את המאגר הידני. ריק אם לא קיים."""
    _migrate_legacy(project_id, kind)
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


def _backup_store(path: Path) -> None:
    """גיבוי המאגר הקיים ל-<file>.bak לפני דריסה (בטיחות)."""
    if not path.exists():
        return
    try:
        import shutil
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    except Exception as e:  # גיבוי כושל לא חוסם שמירה
        logger.warning("Backup of %s failed (non-fatal): %s", path, e)


def save_store(project_id: str, kind: str, df: pd.DataFrame) -> int:
    """שומר את המאגר ל-parquet, מגבה קודם, ומאמת ע"י קריאה חוזרת.

    מחזיר את מספר השורות שנקראו חזרה מהדיסק (אימות אמיתי).
    זורק RuntimeError אם השמירה נכשלה — כדי שה-UI לא יציג 'נשמר' בטעות.
    """
    path = _store_path(project_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup_store(path)
    try:
        df.to_parquet(path, index=False)
    except Exception as e:
        logger.exception("Failed to save manual %s store %s: %s", kind, path, e)
        raise RuntimeError(f"שמירת המאגר נכשלה: {e}") from e
    # ── אימות: קריאה חוזרת מהדיסק וספירה ──
    try:
        reread = pd.read_parquet(path)
    except Exception as e:
        logger.exception("Read-back verification failed for %s: %s", path, e)
        raise RuntimeError(f"אימות השמירה נכשל (קריאה חוזרת): {e}") from e
    if len(reread) != len(df):
        raise RuntimeError(
            f"אימות השמירה נכשל: נכתבו {len(df)} שורות אך נקראו {len(reread)}.")
    # ── מראָה xlsx קריאה (לפתיחה/גיבוי ידני) — best-effort ──
    _write_xlsx_mirror(project_id, kind, df)
    logger.info("Saved + verified manual %s store (%d rows) to %s",
                kind, len(reread), path)
    return len(reread)


def _write_xlsx_mirror(project_id: str, kind: str, df: pd.DataFrame) -> None:
    """כותב עותק xlsx קריא (כותרות עברית) לצד ה-parquet. אינו חוסם בכשל."""
    xpath = _xlsx_path(project_id, kind)
    try:
        labels = column_labels(kind)
        keys = [k for k in column_keys(kind) if k in df.columns]
        disp = df[keys].rename(columns=labels)
        with pd.ExcelWriter(xpath, engine="openpyxl") as w:
            disp.to_excel(w, index=False, sheet_name="נתונים")
    except Exception as e:
        logger.warning("xlsx mirror write failed for %s/%s: %s", project_id, kind, e)


def _import_log_path() -> Path:
    """נתיב קובץ לוג היבוא הידני (xlsx, גלובלי)."""
    from pipeline import MANUAL_ROOT
    return MANUAL_ROOT / "import_log.xlsx"


def append_import_log(project_id: str, project_name: str, kind: str,
                      month: str, summary: dict, status: str,
                      user: str = "") -> None:
    """מוסיף שורה ל-data/manual/import_log.xlsx. אינו חוסם בכשל."""
    path = _import_log_path()
    row = {
        "תאריך ושעה": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "סוג דוח": KINDS.get(kind, {}).get("label", kind),
        "פרויקט": project_name,
        "project_id": project_id,
        "חודש": month or ", ".join(summary.get("saved_months", []) or []),
        "שורות שנשמרו": int(summary.get("saved_count", summary.get("valid_count", 0))),
        "חדשות": int(summary.get("new_count", 0)),
        "כפילויות": int(summary.get("duplicate_count", 0)),
        "עודכנו": int(summary.get("updated_count", 0)),
        'סה"כ בקובץ': int(summary.get("store_after", 0)),
        "סטטוס": status,
        "משתמש": user or "",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = pd.read_excel(path) if path.exists() else pd.DataFrame()
        out = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            out.to_excel(w, index=False, sheet_name="log")
    except Exception as e:
        logger.warning("append_import_log failed (non-fatal): %s", e)


def read_import_log(project_id: str | None = None) -> pd.DataFrame:
    """קורא את לוג היבוא הידני מ-xlsx (אופציונלית מסונן לפרויקט)."""
    path = _import_log_path()
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_excel(path)
    except Exception as e:
        logger.warning("read_import_log failed: %s", e)
        return pd.DataFrame()
    if project_id and "project_id" in df.columns:
        df = df[df["project_id"] == project_id]
    return df.iloc[::-1].reset_index(drop=True)  # החדש למעלה


def delete_store(project_id: str, kind: str) -> bool:
    """מוחק את המאגר (parquet + מראָת xlsx). מחזיר True אם נמחק."""
    path = _store_path(project_id, kind)
    deleted = False
    if path.exists():
        try:
            path.unlink()
            deleted = True
        except Exception as e:
            logger.warning("Failed to delete manual %s store: %s", kind, e)
    xpath = _xlsx_path(project_id, kind)
    if xpath.exists():
        try:
            xpath.unlink()
        except Exception as e:
            logger.warning("Failed to delete xlsx mirror: %s", e)
    return deleted


# ── ולידציה ואבחון ─────────────────────────────────────────────
def _field_filled(kind: str, prepared: pd.DataFrame, field: str) -> pd.Series:
    """Series בוליאני: האם השדה מלא (מספר≠0 / טקסט לא ריק / תאריך תקין)."""
    if field not in prepared.columns:
        return pd.Series(False, index=prepared.index)
    col = prepared[field]
    ckind = column_kind(kind, field)
    if ckind == "date":
        return prepared["month"].notna() & (prepared["month"].astype(str) != "")
    if ckind in ("int", "float"):
        num = pd.to_numeric(col, errors="coerce")
        return num.notna() & (num != 0)
    return col.apply(lambda v: bool(_norm_text(v)))


def validate_incoming(kind: str, prepared: pd.DataFrame) -> pd.Series:
    """Series בוליאני: True לשורות תקינות (כל required_all + כל קבוצת required_any)."""
    if prepared.empty:
        return pd.Series([], dtype=bool)
    cfg = KINDS[kind]
    ok = pd.Series(True, index=prepared.index)
    for field in cfg.get("required_all", []):
        ok &= _field_filled(kind, prepared, field)
    for group in cfg.get("required_any", []):
        any_filled = pd.Series(False, index=prepared.index)
        for field in group:
            any_filled |= _field_filled(kind, prepared, field)
        ok &= any_filled
    return ok


def row_diagnostics(kind: str, prepared: pd.DataFrame) -> pd.DataFrame:
    """טבלת אבחון שורה-שורה: מספר שורה, תאריך, סטטוס, בעיות, אזהרות."""
    cfg = KINDS[kind]
    labels = column_labels(kind)
    rows = []
    for i, (_idx, r) in enumerate(prepared.iterrows(), start=1):
        errors, warns = [], []
        # תאריך
        if not (r.get("month") and str(r.get("month")) != "nan"):
            errors.append("חסר/לא תקין: תאריך")
        # required_all (פרט לתאריך שכבר טופל)
        for field in cfg.get("required_all", []):
            if field == "date":
                continue
            if not _field_filled(kind, prepared.loc[[_idx]], field).iloc[0]:
                errors.append(f"חסר: {labels.get(field, field)}")
        # required_any
        for group in cfg.get("required_any", []):
            filled = any(_field_filled(kind, prepared.loc[[_idx]], f).iloc[0]
                         for f in group)
            if not filled:
                names = " / ".join(labels.get(f, f) for f in group)
                errors.append(f"חסר אחד מ: {names}")
        # warn_any
        for group in cfg.get("warn_any", []):
            filled = any(_field_filled(kind, prepared.loc[[_idx]], f).iloc[0]
                         for f in group)
            if not filled:
                names = " / ".join(labels.get(f, f) for f in group)
                warns.append(f"מומלץ למלא: {names}")
        rows.append({
            "שורה": i,
            "תאריך": _norm_date(r.get("date")) or "—",
            "סטטוס": "תקין" if not errors else "שגיאה",
            "בעיות": " · ".join(errors) if errors else "—",
            "אזהרות": " · ".join(warns) if warns else "—",
        })
    return pd.DataFrame(rows)


# ── ניתוח / יבוא ───────────────────────────────────────────────
def _empty_summary() -> dict:
    return {
        "rows_in_file": 0, "valid_count": 0, "error_count": 0, "warn_count": 0,
        "new_count": 0, "duplicate_count": 0, "updated_count": 0,
        "store_before": 0, "store_after": 0,
        "date_min": None, "date_max": None, "months": [],
        "amount_sum": 0.0, "liters_sum": 0.0, "hours_sum": 0.0,
        # תאימות ל-db.log_import
        "no_date_count": 0, "no_amount_count": 0,
        "debit_sum": 0.0, "credit_sum": 0.0,
    }


def analyze(project_id: str, kind: str, incoming: pd.DataFrame,
            mode: str = "add_new", target_month: str | None = None) -> dict:
    """מנתח יבוא מבלי לשמור — מחזיר סיכום לתצוגה מקדימה.

    incoming: DataFrame בעמודות המערכת (אחרי apply_mapping), לפני prepare.
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

    if "liters" in valid.columns:
        summary["liters_sum"] = float(pd.to_numeric(valid["liters"], errors="coerce").fillna(0).sum())
    if "total_hours" in valid.columns:
        summary["hours_sum"] = float(pd.to_numeric(valid["total_hours"], errors="coerce").fillna(0).sum())
    if "total_cost" in valid.columns:
        summary["amount_sum"] = float(pd.to_numeric(valid["total_cost"], errors="coerce").fillna(0).sum())
    elif "amount" in valid.columns:
        summary["amount_sum"] = float(pd.to_numeric(valid["amount"], errors="coerce").fillna(0).sum())

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
    summary["saved"] = False
    summary["verified_rows"] = 0
    summary["verified_ok"] = False
    summary["store_path"] = str(_store_path(project_id, kind))
    if mode == "check_only":
        return summary

    prepared = prepare_incoming(kind, incoming)
    if prepared.empty:
        return summary
    valid_mask = validate_incoming(kind, prepared)
    valid = prepared[valid_mask].copy()
    # ── בטיחות: לעולם לא לגעת במאגר כשאין שורות תקינות ──
    # מונע ש-replace_month ימחק חודש שלם כשהקלט ריק מתוקף.
    if valid.empty:
        logger.warning("apply_import aborted: 0 valid rows (mode=%s) — store untouched",
                       mode)
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
        incoming_keys = set(valid["key_hash"])
        kept = store[~store["key_hash"].isin(incoming_keys)] if "key_hash" in store.columns else store
        merged = pd.concat([kept, valid], ignore_index=True, sort=False)
    else:  # add_new
        existing = set(store["row_hash"])
        fresh = valid[~valid["row_hash"].isin(existing)]
        merged = pd.concat([store, fresh], ignore_index=True, sort=False)

    if "row_hash" in merged.columns:
        merged = merged.drop_duplicates(subset=["row_hash"], keep="last")
    merged = merged.reset_index(drop=True)
    # save_store מאמת ע"י קריאה חוזרת וזורק אם נכשל
    verified = save_store(project_id, kind, merged)
    summary["store_after"] = len(merged)
    summary["verified_rows"] = verified
    summary["verified_ok"] = (verified == len(merged))
    summary["saved"] = True
    summary["saved_months"] = sorted(valid["month"].dropna().unique().tolist())
    summary["saved_count"] = int(len(valid))

    # ── כתיבה-מקבילה ל-Neon (אחסון קבוע בענן) ──
    # הקובץ המקומי הוא גיבוי; ב-Neon הנתונים שורדים redeploy. write-through
    # זה לא חוסם את השמירה המקומית — אם Neon לא זמין, ממשיכים מקומית בלבד.
    summary["neon_saved"] = False
    summary["neon_verified_ok"] = False
    summary["neon_verified_rows"] = 0
    summary["batch_id"] = None
    try:
        from core import cloud_db
        if cloud_db.is_configured():
            neon = cloud_db.save_entries(
                project_id, kind, valid, mode=mode,
                target_month=target_month,
                source_file=source_file or "הזנה ידנית")
            summary["neon_saved"] = bool(neon.get("neon_saved"))
            summary["neon_verified_ok"] = bool(neon.get("neon_verified_ok"))
            summary["neon_verified_rows"] = int(neon.get("neon_verified_rows", 0))
            summary["neon_store_after"] = int(neon.get("neon_store_after", 0))
            summary["batch_id"] = neon.get("batch_id")
            if neon.get("error"):
                summary["neon_error"] = neon["error"]
    except Exception as e:  # write-through לא חוסם שמירה מקומית
        logger.warning("Neon write-through failed (non-fatal): %s", e)
        summary["neon_error"] = str(e)
    return summary
