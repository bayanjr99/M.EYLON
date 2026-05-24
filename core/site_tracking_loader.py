"""טעינת קובץ מעקב אתר תפעולי (data/projects/<id>/site_tracking.xlsx).

קובץ ידני שמכיל 9 גליונות של נתונים תפעוליים:
    שעות עבודה כלים        → tools_hours
    שעות עבודה עובדים      → employees_hours
    שעות עבודה קבלני משנה  → subcontractors_hours
    סולר                   → fuel (engine_hours + consumption per fueling)
    נוזלים אחרים           → other_fluids
    טיפולים                → treatments (intervals + next service due)
    יומן טיפולים           → treatments_log
    רשימת כלים             → tools_list
    הובלות                 → transports

הקובץ project-wide (לא per-month) כי הוא מכסה כמה חודשים בגליון אחד.
המיקום: data/projects/<project_id>/site_tracking.xlsx
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# שמות גליונות + מילות מפתח לזיהוי
SHEET_KEYS = {
    "tools_hours":             ["שעות עבודה כלים", "שעות כלים"],
    "employees_hours":         ["שעות עבודה עובדים", "שעות עובדים"],
    "subcontractors_hours":    ["שעות עבודה קבלני משנה", "קבלני משנה"],
    "fuel":                    ["סולר"],
    "other_fluids":            ["נוזלים אחרים", "נוזלים"],
    "treatments":              ["טיפולים"],
    "treatments_log":          ["יומן טיפולים"],
    "tools_list":              ["רשימת כלים"],
    "transports":              ["הובלות"],
}


def _find_sheet(sheet_names: list[str], keywords: list[str]) -> str | None:
    """מאתר גליון לפי מילת מפתח (case insensitive substring)."""
    for kw in keywords:
        for sn in sheet_names:
            if kw in sn:
                return sn
    return None


def _read_sheet(xl: pd.ExcelFile, sheet_name: str, header: int = 0) -> pd.DataFrame:
    """קריאה בטוחה - מחזיר DataFrame ריק במקרה של כשלון."""
    try:
        df = xl.parse(sheet_name, header=header)
        # סנן שורות completely-empty
        df = df.dropna(how="all").reset_index(drop=True)
        return df
    except Exception as e:
        logger.warning("Failed to read sheet '%s': %s", sheet_name, e)
        return pd.DataFrame()


def _normalize_hours_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """נרמול גנרי לכל גליון שעות (כלים/עובדים/קבלנים).

    מוציא: date, name_or_tool, license_num (אם יש), start_time, end_time,
    work_hours, section (אם יש), notes.
    """
    if df.empty:
        return df
    rename = {
        "תאריך": "date",
        "שם": "name",
        "שם כלי": "tool_name",
        "מס' כלי": "license_num",
        "מס' רכב": "license_num",
        "בעלים": "owner",
        "שעת התחלה": "start_time",
        "שעת סיום": "end_time",
        "הפסקה": "break",
        "שעות עבודה ללא הפסקה": "work_hours_net",
        "שעות עבודה בשעות כולל הפסקה": "work_hours",
        "סעיף": "section",
        "הערות": "notes",
        "חודש": "month_label",
        "יום": "day_label",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df[df["date"].notna()]
    if "license_num" in df.columns:
        df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
    for col in ("work_hours", "work_hours_net"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "month_label" not in df.columns and "date" in df.columns:
        df["month_label"] = df["date"].dt.strftime("%m-%Y")
    return df.reset_index(drop=True)


def _normalize_fuel_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """נרמול גליון סולר (יש לו header בשורה 0)."""
    if df.empty:
        return df
    # First row is the real header
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    df = df.dropna(how="all").reset_index(drop=True)
    rename = {
        "חודש": "month_label",
        "יום": "day_label",
        "תאריך": "date",
        "מס' כלי": "license_num",
        "שעות מנוע": "engine_hours",
        "תדלוק סולר": "liters",
        "שם כלי": "tool_name",
        "ספירה שעות מנוע": "engine_hours_count",
        "צריכות בפועל לשעה": "lph_actual",
        "צריכות לשעה ממוצע חודשי בפועל": "lph_monthly_avg",
        "הערות": "notes",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df[df["date"].notna()]
    if "license_num" in df.columns:
        df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
    for col in ("engine_hours", "liters", "lph_actual", "lph_monthly_avg"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "month_label" not in df.columns and "date" in df.columns:
        df["month_label"] = df["date"].dt.strftime("%m-%Y")
    return df.reset_index(drop=True)


def _normalize_treatments(df: pd.DataFrame) -> pd.DataFrame:
    """נרמול גליון טיפולים."""
    if df.empty:
        return df
    # First row is header
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    df = df.dropna(how="all").reset_index(drop=True)
    rename = {
        "שם כלי": "tool_name",
        "מספר רישוי": "license_num",
        "בעלים": "owner",
        "שעות מנוע  - משיכה": "engine_hours_current",
        "שעות מנוע בטיפול": "engine_hours_last_service",
        "תאריך": "last_service_date",
        "מרווח טיפול": "service_interval",
        "טיפול הבא": "next_service_hours",
        "הפרש": "hours_until_service",
        "התראה": "alert",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "license_num" in df.columns:
        df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
    if "last_service_date" in df.columns:
        df["last_service_date"] = pd.to_datetime(df["last_service_date"], errors="coerce")
    for col in ("engine_hours_current", "engine_hours_last_service",
                "service_interval", "next_service_hours", "hours_until_service"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _normalize_tools_list(df: pd.DataFrame) -> pd.DataFrame:
    """נרמול רשימת כלים."""
    if df.empty:
        return df
    rename = {
        "מספר רישוי": "license_num",
        "סוג כלי": "tool_type",
        "שם כלי": "tool_name",
        "בעלים": "owner",
        "מרווח טיפול": "service_interval",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "license_num" in df.columns:
        df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
        df = df[df["license_num"].notna()]
    return df.reset_index(drop=True)


def _normalize_other_fluids(df: pd.DataFrame) -> pd.DataFrame:
    """נרמול נוזלים אחרים."""
    if df.empty:
        return df
    # First row is header
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    df = df.dropna(how="all").reset_index(drop=True)
    rename = {
        "חודש": "month_label", "יום": "day_label", "תאריך": "date",
        "מס' כלי": "license_num", "שעות מנוע": "engine_hours",
        "שם כלי": "tool_name", "אוריאה": "urea_l", "שמן מנוע": "engine_oil_l",
        "שמן הידראלויקה I68": "hydraulic_oil_l", "שמן מנוע2": "engine_oil_2_l",
        "הערות ": "notes", "הערות": "notes",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df[df["date"].notna()]
    if "license_num" in df.columns:
        df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
    for col in ("urea_l", "engine_oil_l", "hydraulic_oil_l", "engine_oil_2_l", "engine_hours"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def load_site_tracking(file_path: str | Path) -> dict[str, pd.DataFrame]:
    """טוען את קובץ מעקב האתר ומחזיר dict של 9 DataFrames מנורמלים.

    מפתחות אפשריים: tools_hours, employees_hours, subcontractors_hours,
    fuel, other_fluids, treatments, treatments_log, tools_list, transports.
    כל מפתח חסר → DataFrame ריק.
    """
    path = Path(file_path)
    if not path.exists():
        logger.info("site_tracking.xlsx not found at %s (optional)", path)
        return {k: pd.DataFrame() for k in SHEET_KEYS}

    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to open site_tracking: %s", e)
        return {k: pd.DataFrame() for k in SHEET_KEYS}

    out: dict[str, pd.DataFrame] = {}
    for key, keywords in SHEET_KEYS.items():
        sn = _find_sheet(xl.sheet_names, keywords)
        if sn is None:
            out[key] = pd.DataFrame()
            continue

        raw = _read_sheet(xl, sn)
        if key in ("tools_hours", "employees_hours", "subcontractors_hours"):
            out[key] = _normalize_hours_sheet(raw)
        elif key == "fuel":
            out[key] = _normalize_fuel_sheet(raw)
        elif key == "other_fluids":
            out[key] = _normalize_other_fluids(raw)
        elif key == "treatments":
            out[key] = _normalize_treatments(raw)
        elif key == "tools_list":
            out[key] = _normalize_tools_list(raw)
        else:
            out[key] = raw  # log/transports - שמור כמו שהוא

    counts = {k: len(v) for k, v in out.items() if not v.empty}
    logger.info("Loaded site_tracking: %s", counts)
    return out
