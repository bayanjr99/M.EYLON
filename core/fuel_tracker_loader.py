"""טעינת קובץ "מעקב סולר וטיפולים - כלי צמה.xlsx" — מקור אמת לתדלוקים.

הקובץ project-wide ויושב בתיקיית הפרויקט (data/projects/<id>/).
מכיל גליון "יומן סולר" עם כל התדלוקים — שורה לכל אירוע תדלוק.

עמודות מצופות בגליון "יומן סולר":
    אתר, תאריך, מספר רישוי, שם כלי, בעלים, שעות מנוע,
    כמות סולר (ל'), ספירת שעות מנוע, צריכה לשעה (ל'),
    צריכה מסוננת (ל'/ש'), סטטוס חריגה.

הבחנה קריטית:
    "שעות מנוע"          = קריאת מונה מצטברת (לא משתמשים לחישוב ל'/ש')
    "ספירת שעות מנוע"    = שעות עבודה בפועל מאז התדלוק הקודם (delta)
    "צריכה מסוננת"       = ל'/ש' אחרי ניקוי קפיצות לא תקינות (preferred for display)
    "צריכה לשעה"         = ל'/ש' גלמית (fallback)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from utils.hebrew import contains, match_normalize, similarity

logger = logging.getLogger(__name__)


# שמות גליון אפשריים (התאמה רכה)
SHEET_KEYWORDS = ["יומן סולר", "יומן תדלוק"]

# מילות מפתח לזיהוי הקובץ בתיקיית הפרויקט (אם השם לא בדיוק)
FILE_KEYWORDS = ["מעקב סולר וטיפולים", "מעקב סולר", "fuel_tracker"]

# מיפוי שמות עמודות בעברית → אנגלית
COLUMN_MAP = {
    "אתר":                    "site",
    "תאריך":                  "date",
    "מספר רישוי":             "license_num",
    "שם כלי":                 "tool_name",
    "בעלים":                  "owner",
    "שעות מנוע":              "engine_hours",       # קריאת מונה מצטברת
    "כמות סולר (ל')":         "liters",
    "ספירת שעות מנוע":        "work_hours",         # שעות עבודה בפועל (delta)
    "צריכה לשעה (ל')":        "lph_calculated",
    "צריכה מסוננת (ל'/ש')":   "lph_filtered",
    "סטטוס חריגה":            "anomaly_status",
}

OUTPUT_COLS = list(COLUMN_MAP.values())


def _find_file(project_dir: Path) -> Path | None:
    """מאתר את קובץ "מעקב סולר וטיפולים" בתיקיית הפרויקט."""
    if not project_dir.exists():
        return None
    for f in project_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
            continue
        if f.name.startswith("~$"):
            continue
        name = f.name
        if any(kw in name for kw in FILE_KEYWORDS):
            return f
    return None


def _find_sheet(sheet_names: list[str]) -> str | None:
    """מאתר את גליון "יומן סולר" (התאמה רכה)."""
    for kw in SHEET_KEYWORDS:
        for sn in sheet_names:
            if kw in sn:
                return sn
    return None


def load_fuel_tracker(project_dir: Path, site_name: str | None = None) -> pd.DataFrame:
    """טוען את קובץ מעקב הסולר לפרויקט נתון.

    Args:
        project_dir: נתיב לתיקיית הפרויקט (data/projects/<id>/).
        site_name: שם האתר לסינון (השוואה רכה). None = ללא סינון.

    Returns:
        DataFrame עם עמודות OUTPUT_COLS, אחרי סינון לפי האתר.
        DataFrame ריק אם הקובץ/הגליון לא נמצא.
    """
    file = _find_file(project_dir)
    if file is None:
        logger.info("fuel_tracker file not found in %s", project_dir)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        sheet = _find_sheet(xl.sheet_names)
        if sheet is None:
            logger.warning("fuel_tracker: no 'יומן סולר' sheet in %s (sheets: %s)",
                          file.name, xl.sheet_names)
            return pd.DataFrame(columns=OUTPUT_COLS)
        df = xl.parse(sheet)
    except Exception as e:
        logger.exception("Failed to read fuel_tracker file %s: %s", file, e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    # נרמול שמות עמודות
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    # ודא שכל העמודות בסכמה קיימות
    for col in OUTPUT_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    # סנן שורות ריקות לחלוטין
    df = df.dropna(how="all", subset=["date", "license_num", "liters"]).reset_index(drop=True)

    # נרמול ערכים מספריים
    for num_col in ["liters", "engine_hours", "work_hours",
                    "lph_calculated", "lph_filtered"]:
        df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

    # נרמול תאריך
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # סינון לפי אתר (השוואה רכה לפי utils.hebrew + similarity fallback)
    if site_name:
        target = str(site_name).strip()
        if target:
            mask = df["site"].apply(lambda s: _site_matches(s, target))
            df = df[mask].reset_index(drop=True)

    # החזר רק את העמודות בסכמה (סדר עקבי)
    return df[OUTPUT_COLS]


# סף similarity מינימלי להתאמת אתר. 0.5 = חצי מהטוקנים חופפים.
# מאפשר טעויות הקלדה שכיחות (לדוגמה "נחלית עילית" ↔ "נחלת עילית").
SITE_SIMILARITY_THRESHOLD = 0.5


def _site_matches(site: object, target: str) -> bool:
    """3-tier matching: exact normalized → contains → similarity."""
    if not isinstance(site, str):
        return False
    # tier 1: exact (after normalization)
    if match_normalize(site) == match_normalize(target):
        return True
    # tier 2: token containment either direction
    if contains(target, site) or contains(site, target):
        return True
    # tier 3: fuzzy similarity (handles single-letter typos)
    if similarity(site, target) >= SITE_SIMILARITY_THRESHOLD:
        return True
    return False


def list_sites_in_file(project_dir: Path) -> list[str]:
    """מחזיר רשימת אתרים ייחודיים בקובץ (לדיאגנוסטיקה / UI).

    שימושי להראות למשתמש למה הסינון לפי project.site_name לא תפס שורות.
    """
    file = _find_file(project_dir)
    if file is None:
        return []
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        sheet = _find_sheet(xl.sheet_names)
        if sheet is None:
            return []
        df = xl.parse(sheet, usecols=["אתר"])
    except Exception as e:
        logger.warning("list_sites_in_file failed: %s", e)
        return []
    return sorted(s for s in df["אתר"].dropna().astype(str).unique() if s.strip())


# ── Anomaly classification ──────────────────────────────────────

# ספים לזיהוי חריגות מערכת (משלים את "סטטוס חריגה" מהאקסל)
WORK_HOURS_MAX = 720          # > חודש של עבודה רצופה מתדלוק לתדלוק = קפיצה
LPH_MIN_REASONABLE = 0.5      # ל'/ש' מתחת לזה לכלי צמ"ה — חשוד
LPH_MAX_REASONABLE = 100      # מעל זה חריג גבוה (גנרטור גדול = 60-70)


def classify_row(row: pd.Series) -> str:
    """מסווג שורת תדלוק לסטטוס תצוגה.

    משלב את "סטטוס חריגה" מהאקסל (אם קיים ומלא) עם בדיקות מערכת
    נוספות (שדות חסרים, ערכים בלתי-הגיוניים).

    Returns:
        מחרוזת סטטוס. ערכים אפשריים:
            "✓ תקין"
            "— לא ניתן לחשב"  (חסרים נתונים)
            "⚠ כלי ללא מס' רישוי"
            "⚠ ספירת שעות שלילית"
            "🔴 קריאת מונה חריגה"
            "🔴 צריכה לא הגיונית"
            "🔴 צריכה גבוהה במיוחד"
            <ערך מהאקסל אם קיים>
    """
    # 1. כלי ללא רישוי — תמיד נסמן (לא תלוי בערכי אקסל)
    lic = row.get("license_num")
    if pd.isna(lic) or str(lic).strip() in ("", "0"):
        return "⚠ כלי ללא מס' רישוי"

    # 2. ליטרים חסרים
    liters = row.get("liters")
    if pd.isna(liters) or float(liters) <= 0:
        return "⚠ אין נתון ליטרים"

    # 3. שעות עבודה (ספירת שעות מנוע) חסרות — אבל יש ליטרים
    work_hours = row.get("work_hours")
    if pd.isna(work_hours):
        return "— לא ניתן לחשב"
    work_hours = float(work_hours)
    if work_hours < 0:
        return "⚠ ספירת שעות שלילית"
    if work_hours == 0:
        return "— לא ניתן לחשב"
    if work_hours > WORK_HOURS_MAX:
        return "🔴 קריאת מונה חריגה"

    # 4. בדיקת צריכה (preferred: מסוננת, fallback: גלמית)
    lph_f = row.get("lph_filtered")
    lph_c = row.get("lph_calculated")
    lph = lph_f if pd.notna(lph_f) else lph_c
    if pd.notna(lph):
        lph = float(lph)
        if lph < LPH_MIN_REASONABLE:
            return "🔴 צריכה לא הגיונית — בדוק מונה"
        if lph > LPH_MAX_REASONABLE:
            return "🔴 צריכה גבוהה במיוחד"

    # 5. סטטוס מהאקסל גובר אם קיים ולא נראה תקין
    xlsx_status = row.get("anomaly_status")
    if pd.notna(xlsx_status) and str(xlsx_status).strip() != "":
        s = str(xlsx_status).strip()
        # אם האקסל סימן תקין — אז תקין
        if "תקין" in s:
            return "✓ תקין"
        # אחרת — שמור על הסטטוס המקורי מהאקסל
        return s

    return "✓ תקין"


def apply_classification(df: pd.DataFrame) -> pd.DataFrame:
    """מוסיף עמודת `status` (סטטוס תצוגה משולב) ל-DataFrame.

    גם מוסיף עמודת `lph_display` = הצריכה המועדפת להצגה
    (מסוננת אם קיימת, אחרת גלמית, NaN אם work_hours בלתי-תקין).
    """
    if df.empty:
        out = df.copy()
        out["status"] = pd.Series(dtype=str)
        out["lph_display"] = pd.Series(dtype=float)
        return out

    out = df.copy()

    # status
    out["status"] = out.apply(classify_row, axis=1)

    # lph_display: prefer filtered, fall back to calculated
    out["lph_display"] = out["lph_filtered"].where(
        out["lph_filtered"].notna(), out["lph_calculated"]
    )

    # אם work_hours לא תקין — אל תציג ל'/ש' (כדי לא להטעות עם 0.0)
    bad_wh = out["work_hours"].isna() | (out["work_hours"] <= 0)
    out.loc[bad_wh, "lph_display"] = pd.NA

    return out


# ── Public API ──────────────────────────────────────────────────

def is_anomaly_status(status: str | float) -> bool:
    """True אם הסטטוס דורש בדיקה (לא 'תקין' ולא ריק)."""
    if pd.isna(status):
        return False
    s = str(status).strip()
    if not s:
        return False
    return "תקין" not in s and not s.startswith("✓")
