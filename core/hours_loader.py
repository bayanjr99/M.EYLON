"""טעינת דוח שעות עבודה כלים מהמזכירה.

המבנה משתנה בין קבצים, אך כולל בדרך כלל:
- גליון "רשימת כלים" - רשימת הכלים בפרויקט.
- גליון "שעות עבודה כלים" - הדוח עצמו (PRIMARY).
- גליון "סולר" - יומן סולר ידני (גיבוי).

עמודות בגליון "שעות עבודה כלים":
    תאריך, מס' כלי, שם כלי, שעת התחלה, שעת סיום,
    שעות עבודה בשעות כולל הפסקה (← work_hours), הפסקה.

לעיתים יש שורות פגומות (ערכים שליליים/אבסורדיים) - יש לסנן.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


HOURS_SHEET_NAMES = [
    "שעות עבודה כלים",
    "שעות עבודה",
    "שעות כלים",
]

COLUMN_MAP = {
    "תאריך": "date",
    "מס' כלי": "license_num",
    "מספר כלי": "license_num",
    "שם כלי": "tool_name",
    "שעת התחלה": "start_time",
    "שעת סיום": "end_time",
    "שעות עבודה בשעות כולל הפסקה": "work_hours",
    "שעות עבודה": "work_hours",
    "הפסקה": "break_hours",
}

OUTPUT_COLS = [
    "date", "license_num", "tool_name",
    "start_time", "end_time", "work_hours", "break_hours",
]

# שעות יום חוקיות - מחוץ לטווח = שורה פגומה.
MIN_WORK_HOURS = 0.0
MAX_WORK_HOURS = 16.0


def load_hours(file_path: str | Path) -> pd.DataFrame:
    """טוען דוח שעות כלים מ-XLSX.

    Returns:
        DataFrame עם עמודות: date, license_num, tool_name,
        start_time, end_time, work_hours, break_hours.
        שורות פגומות מסוננות החוצה (עם warning בלוג).
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("hours file not found: %s", path)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to open hours xlsx: %s", e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    sheet_name = _pick_sheet(xl.sheet_names)
    if sheet_name is None:
        logger.warning("No matching hours sheet found in %s. Sheets: %s",
                       path.name, xl.sheet_names)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        df = xl.parse(sheet_name)
    except Exception as e:
        logger.exception("Failed to parse sheet '%s': %s", sheet_name, e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})
    for col in OUTPUT_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
    df["work_hours"] = pd.to_numeric(df["work_hours"], errors="coerce")
    df["break_hours"] = pd.to_numeric(df["break_hours"], errors="coerce")

    before = len(df)
    df = df[df["date"].notna() & df["license_num"].notna()]

    # סינון שורות עם ערכי שעות אבסורדיים (negative או > 16)
    invalid_mask = df["work_hours"].isna() | (
        (df["work_hours"] < MIN_WORK_HOURS) | (df["work_hours"] > MAX_WORK_HOURS)
    )
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        logger.warning("Dropped %d rows with invalid work_hours from %s",
                       invalid_count, path.name)
    df = df[~invalid_mask].reset_index(drop=True)

    logger.info("Loaded %d/%d hours rows from %s (sheet: %s)",
                len(df), before, path.name, sheet_name)
    return df[OUTPUT_COLS]


def aggregate_by_tool_month(df_hours: pd.DataFrame) -> pd.DataFrame:
    """מקבץ שעות לפי (license_num, month).

    Returns:
        DataFrame עם: license_num, tool_name, month,
        total_work_hours, work_days, first_date, last_date.
    """
    cols = ["license_num", "tool_name", "month",
            "total_work_hours", "work_days", "first_date", "last_date"]
    if df_hours.empty:
        return pd.DataFrame(columns=cols)

    df = df_hours.copy()
    df["month"] = pd.to_datetime(df["date"]).dt.strftime("%m-%Y")

    grouped = (
        df.groupby(["license_num", "month"], dropna=False)
          .agg(
              tool_name=("tool_name", lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
              total_work_hours=("work_hours", "sum"),
              work_days=("date", "nunique"),
              first_date=("date", "min"),
              last_date=("date", "max"),
          )
          .reset_index()
    )
    return grouped[cols]


def _pick_sheet(available: list[str]) -> str | None:
    """מאתר את שם הגליון המכיל את דוח השעות.

    מנסה בסדר HOURS_SHEET_NAMES; אם לא נמצא, מחפש גליון
    שמכיל "שעות" בשם.
    """
    for name in HOURS_SHEET_NAMES:
        if name in available:
            return name
    for name in available:
        if "שעות" in name:
            return name
    return None
