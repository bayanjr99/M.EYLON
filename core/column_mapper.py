"""זיהוי גמיש של עמודות בקבצי מקור משתנים.

מטרה: למנוע מצב שבו הלואדר ממפה את ה-engine_hours לעמודת liters
(או כל בלבול דומה) רק בגלל שהשם בקובץ המקור שונה.

עקרון:
1. לכל "תפקיד" (target) — רשימת aliases (שמות מקובלים בעברית/אנגלית).
2. רשימת negative_aliases — שמות שאסור שייבחרו (גם אם דומים בטעות).
3. detect_column() — בוחר את התאמה הטובה ביותר; מציין רמת בטחון.
4. quality_check() — בדיקת איכות לסדרה (טווח, אחוז ריק, התפלגות).
5. Persistence: data/projects/<pid>/column_mapping.json לזכור בחירת משתמש.

API ציבורי:
    detect_column(df, target) → (chosen_col, confidence, candidates)
    quality_check(series, target) → list[dict] warnings
    load_mapping(project_id) → dict
    save_mapping(project_id, mapping) → bool
    apply_mapping(df, mapping) → df (עם override של בחירת המשתמש)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)


# ── Aliases per target ──────────────────────────────────────
# רשימה ראשונה = preferred match (מנוקדת ראשונה)
ALIASES: dict[str, list[str]] = {
    "liters": [
        "תדלוק סולר",
        "כמות סולר",
        "כמות דלק",
        "כמות ליטרים",
        "ליטרים",
        "ליטר",
        "כמות",
        "fuel_liters",
        "liters",
        "qty_liters",
        "diesel_qty",
        "diesel_liters",
    ],
    "engine_hours": [
        "שעות מנוע",
        "ספירת שעות מנוע",
        "מונה שעות מנוע",
        "engine_hours",
        "engine_hr",
        "hours_meter",
    ],
    "work_hours": [
        "שעות עבודה",
        "שעות עבודה נטו",
        "שעות בפועל",
        "work_hours",
        "actual_hours",
        "hours_worked",
    ],
    "license_num": [
        "מס' רישוי",
        "מספר רישוי",
        "מס רישוי",
        "מס' כלי",
        "מספר כלי",
        "license_num",
        "license",
        "vehicle_id",
        "plate",
    ],
    "tool_name": [
        "שם כלי",
        "שם הכלי",
        "כלי",
        "tool_name",
        "equipment_name",
        "vehicle_name",
    ],
    "date": [
        "תאריך",
        "date",
        "תאריך תדלוק",
        "תאריך פעולה",
    ],
    "supplier": [
        "ספק",
        "שם ספק",
        "supplier",
        "vendor",
        "תחנה",
        "תחנת דלק",
    ],
    "invoice_num": [
        "מס' חשבונית",
        "מספר חשבונית",
        "חשבונית",
        "invoice_num",
        "invoice",
        "אסמכתא",
    ],
    "amount": [
        "סכום",
        "סה\"כ",
        "סך הכל",
        "amount",
        "total",
        "total_cost",
    ],
    "price_per_liter": [
        "מחיר לליטר",
        "מחיר ליטר",
        "₪ לליטר",
        "price_per_liter",
        "unit_price",
    ],
}

# Negative — never map these names to liters
NEGATIVE_FOR_LITERS = {
    "שעות מנוע", "שעות עבודה", "מונה", "קריאת מונה",
    "מס' רישוי", "מספר רישוי", "מס רישוי", "מס' כלי", "מספר כלי",
    "סכום", "מחיר", "מחיר לליטר", "מחיר ליטר",
    "engine_hours", "work_hours", "hours_meter", "license_num",
    "license", "vehicle_id", "amount", "total", "price",
    "price_per_liter", "unit_price",
}


# ── Mapping JSON I/O ────────────────────────────────────────
def _mapping_path(project_id: str) -> Path:
    from pipeline import PROJECTS_ROOT
    return PROJECTS_ROOT / project_id / "column_mapping.json"


def load_mapping(project_id: str) -> dict[str, str]:
    """טוען את ה-mapping השמור לפרויקט. מחזיר dict ריק אם לא קיים."""
    path = _mapping_path(project_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to load column_mapping.json for %s: %s", project_id, e)
        return {}


def save_mapping(project_id: str, mapping: dict[str, str]) -> bool:
    """שומר את ה-mapping. מחזיר True אם הצליח."""
    path = _mapping_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        logger.info("Saved column_mapping.json for %s: %s", project_id, mapping)
        return True
    except Exception as e:
        logger.exception("Failed to save column_mapping.json: %s", e)
        return False


# ── Detection ────────────────────────────────────────────────
def _normalize_name(s: str) -> str:
    """משווה שמות עמודות אחרי הסרת רווחים, גרשיים, וניקוד."""
    if s is None:
        return ""
    out = str(s).strip().lower()
    # הסר גרשיים, מקפים, נקודות, רווחים מיותרים
    out = re.sub(r"[\"'`׳״\-_.,()\[\]]+", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def detect_column(df: pd.DataFrame, target: str,
                    user_choice: str | None = None) -> dict:
    """מזהה את העמודה המתאימה ל-target ב-DataFrame.

    Args:
        df: DataFrame עם העמודות מהקובץ המקור.
        target: שם ה-target (למשל "liters" / "engine_hours" / "license_num").
        user_choice: אם הוגדר ע"י המשתמש - לקחת אותו (override).

    Returns dict:
        {chosen: str | None, confidence: "user"/"exact"/"alias"/"none",
         candidates: list[str], rejected: list[str], reason: str}
    """
    # df יכול להיות "ריק" משורות אבל עם עמודות - די לנו בעמודות
    if df is None or len(df.columns) == 0 or target not in ALIASES:
        return {"chosen": None, "confidence": "none", "candidates": [],
                "rejected": [], "reason": "no data"}

    aliases = ALIASES[target]
    cols = list(df.columns)
    norm_cols = {col: _normalize_name(col) for col in cols}

    # 1. בחירת משתמש (אם קיימת ועדיין רלוונטית)
    if user_choice and user_choice in cols:
        return {"chosen": user_choice, "confidence": "user",
                "candidates": [user_choice], "rejected": [],
                "reason": "בחירת משתמש מ-column_mapping.json"}

    # 2. exact match לפי alias מועדף
    candidates = []
    rejected = []
    for alias in aliases:
        norm_alias = _normalize_name(alias)
        for col, ncol in norm_cols.items():
            if ncol == norm_alias:
                # בדוק שזה לא negative
                if target == "liters" and any(
                    _normalize_name(neg) == ncol for neg in NEGATIVE_FOR_LITERS
                ):
                    rejected.append(col)
                    continue
                candidates.append(col)

    if candidates:
        return {"chosen": candidates[0], "confidence": "exact",
                "candidates": candidates, "rejected": rejected,
                "reason": f"התאמה מדויקת ל-alias '{aliases[0]}'"}

    # 3. partial match - העמודה מכילה את ה-alias
    for alias in aliases:
        norm_alias = _normalize_name(alias)
        for col, ncol in norm_cols.items():
            if norm_alias in ncol and len(norm_alias) >= 3:
                # negative check
                if target == "liters" and any(
                    _normalize_name(neg) in ncol for neg in NEGATIVE_FOR_LITERS
                ):
                    rejected.append(col)
                    continue
                candidates.append(col)

    if candidates:
        return {"chosen": candidates[0], "confidence": "alias",
                "candidates": candidates, "rejected": rejected,
                "reason": f"התאמה חלקית ל-alias '{aliases[0]}'"}

    return {"chosen": None, "confidence": "none",
            "candidates": [], "rejected": rejected,
            "reason": f"לא נמצאה עמודה תואמת ל-{target}"}


# ── Quality check ────────────────────────────────────────────
def quality_check(series: pd.Series, target: str) -> list[dict]:
    """בודק שהערכים בסדרה הגיוניים לטיפוס ה-target.

    מחזיר רשימת אזהרות (יכולה להיות ריקה אם הכל בסדר).
    """
    if series is None or series.empty:
        return [{"level": "warn", "message": "הסדרה ריקה"}]

    s = pd.to_numeric(series, errors="coerce")
    n_total = len(s)
    n_nan = int(s.isna().sum())
    n_zero = int((s == 0).sum())
    s_valid = s.dropna()
    if s_valid.empty:
        return [{"level": "warn", "message": "אין ערכים מספריים תקפים בעמודה"}]

    min_v = float(s_valid.min())
    max_v = float(s_valid.max())
    mean_v = float(s_valid.mean())

    warnings = []

    # אחוז ריק
    pct_nan = (n_nan / n_total * 100) if n_total else 0
    if pct_nan > 50:
        warnings.append({
            "level": "warn",
            "message": f"{pct_nan:.0f}% מהשורות ריקות בעמודה ({n_nan}/{n_total})",
        })

    # אחוז אפסים
    pct_zero = (n_zero / n_total * 100) if n_total else 0
    if pct_zero > 30:
        warnings.append({
            "level": "warn",
            "message": f"{pct_zero:.0f}% מהשורות הן 0 ({n_zero}/{n_total}) - "
                       f"ייתכן שהעמודה הלא נכונה נבחרה",
        })

    # שליליים
    n_neg = int((s_valid < 0).sum())
    if n_neg > 0 and target in ("liters", "engine_hours", "work_hours"):
        warnings.append({
            "level": "warn",
            "message": f"{n_neg} ערכים שליליים — לא אופייני ל-{target}",
        })

    # ערכים חריגים לפי target
    if target == "liters":
        # תדלוק יחיד טיפוסי: 50-500 ליטר. מעל 5000 - חריג מאוד.
        if max_v > 5000:
            warnings.append({
                "level": "warn",
                "message": f"ערך מקסימלי {max_v:,.0f} ליטר — חריג. "
                           f"ייתכן שהעמודה היא 'שעות מנוע' (מונה) ולא ליטרים. "
                           f"שעות מנוע נעות לרוב בין 1,000 ל-50,000.",
            })
        if mean_v > 2000:
            warnings.append({
                "level": "warn",
                "message": f"ממוצע {mean_v:,.0f} ליטר לתדלוק יחיד — לא הגיוני. "
                           f"לרוב התדלוק היומי נע בין 50 ל-1,000 ליטר.",
            })

    elif target == "engine_hours":
        # שעות מנוע נעות בין 0 ל-50,000 (מצטבר). יש לוודא שזה לא 277 (ליטרים)
        if max_v < 100:
            warnings.append({
                "level": "info",
                "message": f"ערך מקסימלי {max_v:.0f} — נמוך לשעות מנוע מצטברות. "
                           f"ייתכן שזו עמודה חודשית או יומית, או שהעמודה היא ליטרים.",
            })

    elif target == "license_num":
        # מס' רישוי 5-8 ספרות
        if min_v < 100 or max_v > 999_999_999:
            warnings.append({
                "level": "info",
                "message": f"טווח {min_v:,.0f}-{max_v:,.0f} — חורג מטווח מס' רישוי",
            })

    return warnings


# ── Apply mapping ────────────────────────────────────────────
def apply_mapping(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """ממפה את העמודות ב-df לפי mapping (source_col → target_name).

    אם target_name כבר קיים - יוחלף.
    שאר העמודות נשארות.
    """
    if df is None or df.empty or not mapping:
        return df
    out = df.copy()
    for target, source_col in mapping.items():
        if source_col and source_col in out.columns:
            # אם target כבר קיים תחת שם אחר - מחק
            if target in out.columns and target != source_col:
                out = out.drop(columns=[target])
            out = out.rename(columns={source_col: target})
    return out


# ── דוח זיהוי לכל ה-targets ──────────────────────────────────
def detect_all(df: pd.DataFrame, project_id: str | None = None,
                targets: list[str] | None = None) -> dict[str, dict]:
    """מריץ detect_column לכל target ומחזיר דוח מאוחד.

    אם project_id - טוען את ה-mapping השמור.
    """
    if targets is None:
        targets = list(ALIASES.keys())
    user_mapping = load_mapping(project_id) if project_id else {}
    return {t: detect_column(df, t, user_mapping.get(t)) for t in targets}
