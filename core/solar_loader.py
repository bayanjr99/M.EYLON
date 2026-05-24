"""טעינת דוח תדלוק (פוינטר/דלקן).

עמודות בקובץ:
    אתר, תאריך, מספר רישוי, שם כלי, בעלים, שעות מנוע,
    כמות סולר (ל'), ספירת שעות מנוע, צריכה לשעה (ל'),
    צריכה מסוננת (ל'/ש'), סטטוס חריגה.

הערה: הקובץ מולטי-פרויקטי. חובה לסנן לפי שם הפרויקט.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from utils.hebrew import contains, match_normalize

logger = logging.getLogger(__name__)


# מיפוי שמות עמודות בעברית → אנגלית
COLUMN_MAP = {
    "אתר": "site",
    "תאריך": "date",
    "מספר רישוי": "license_num",
    "שם כלי": "tool_name",
    "בעלים": "owner",
    "שעות מנוע": "engine_hours",
    "כמות סולר (ל')": "liters",
    "ספירת שעות מנוע": "engine_hours_count",
    "צריכה לשעה (ל')": "lph_calculated",
    "צריכה מסוננת (ל'/ש')": "lph_filtered",
    "סטטוס חריגה": "anomaly_status",
}

OUTPUT_COLS = [
    "site", "date", "license_num", "tool_name", "owner",
    "engine_hours", "liters", "engine_hours_count",
    "lph_calculated", "lph_filtered", "anomaly_status",
]


def load_solar(file_path: str | Path, project_site_name: str) -> pd.DataFrame:
    """טוען דוח תדלוק XLSX ומסנן לפי שם פרויקט.

    Args:
        file_path: נתיב לקובץ solar.xlsx.
        project_site_name: שם האתר/פרויקט לסינון (עמודת "אתר").
                           ההשוואה רכה (utils.hebrew.contains).

    Returns:
        DataFrame עם עמודות מנורמלות באנגלית, אחרי סינון פרויקט.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("solar file not found: %s", path)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read solar xlsx: %s", e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    # נרמול שמות עמודות
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    # ודא שכל העמודות בסכמה קיימות (אם חסרות - מוסיף ריקות)
    for col in OUTPUT_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    # סינון לפי שם פרויקט (השוואה רכה)
    if "site" in df.columns and project_site_name:
        mask = df["site"].apply(
            lambda s: isinstance(s, str) and (
                contains(project_site_name, s)
                or contains(s, project_site_name)
                or match_normalize(s) == match_normalize(project_site_name)
            )
        )
        df = df[mask]

    # המרת טיפוסים
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for num_col in ("engine_hours", "liters", "engine_hours_count",
                    "lph_calculated", "lph_filtered"):
        df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
    df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")

    # סינון שורות ללא תאריך / ללא ליטרים
    df = df[df["date"].notna() & df["liters"].notna() & (df["liters"] > 0)]
    df = df.reset_index(drop=True)

    logger.info("Loaded %d solar rows for site '%s'", len(df), project_site_name)
    return df[OUTPUT_COLS]


def aggregate_by_tool_month(df_solar: pd.DataFrame) -> pd.DataFrame:
    """מקבץ תדלוקים לפי (license_num, month).

    Returns:
        DataFrame עם: license_num, tool_name, month,
        total_liters, fuel_events, first_date, last_date.
    """
    cols = ["license_num", "tool_name", "month",
            "total_liters", "fuel_events", "first_date", "last_date"]
    if df_solar.empty:
        return pd.DataFrame(columns=cols)

    df = df_solar.copy()
    df["month"] = pd.to_datetime(df["date"]).dt.strftime("%m-%Y")

    grouped = (
        df.groupby(["license_num", "month"], dropna=False)
          .agg(
              tool_name=("tool_name", lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
              total_liters=("liters", "sum"),
              fuel_events=("liters", "count"),
              first_date=("date", "min"),
              last_date=("date", "max"),
          )
          .reset_index()
    )
    return grouped[cols]
