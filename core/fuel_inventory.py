"""טעינת מאזן מלאי סולר ידני.

הקובץ fuel_inventory.xlsx (אופציונלי, ידני) - לרשום מצב מלאי לפי חודש:

עמודות (בעברית - הלואדר ינרמל):
    חודש (MM-YYYY) | מלאי פתיחה (ל') | מלאי סגירה (ל')

לוגיקת חישוב:
    מלאי פתיחה + קניות סולר - שימושים = מלאי סגירה צפוי
    הפרש = מלאי סגירה צפוי - מלאי סגירה בפועל

הפרש > 0 = חוסר בלתי מוסבר. הפרש < 0 = עודף (טעות במדידה?).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


COLUMN_MAP = {
    "חודש": "month",
    "month": "month",
    "מלאי פתיחה (ל')": "opening_l",
    "מלאי פתיחה": "opening_l",
    "opening_l": "opening_l",
    "opening": "opening_l",
    "מלאי סגירה (ל')": "closing_l",
    "מלאי סגירה": "closing_l",
    "closing_l": "closing_l",
    "closing": "closing_l",
}

OUTPUT_COLS = ["month", "opening_l", "closing_l"]


def load_fuel_inventory(file_path: str | Path) -> pd.DataFrame:
    """טוען fuel_inventory.xlsx. מחזיר DataFrame ריק אם חסר.

    Returns DataFrame עם month / opening_l / closing_l.
    """
    path = Path(file_path)
    if not path.exists():
        logger.info("fuel_inventory.xlsx not found at %s (optional)", path)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read fuel_inventory: %s", e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})
    for c in OUTPUT_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    df["month"] = df["month"].astype(str).str.strip()
    df["opening_l"] = pd.to_numeric(df["opening_l"], errors="coerce")
    df["closing_l"] = pd.to_numeric(df["closing_l"], errors="coerce")
    df = df[df["month"].notna() & (df["month"] != "")]
    return df[OUTPUT_COLS].reset_index(drop=True)


def compute_balance(
    inventory: pd.DataFrame,
    fuel_purchases_per_month: dict[str, float],  # month → liters bought
    fuel_usage_per_month: dict[str, float],       # month → liters used
) -> pd.DataFrame:
    """חישוב מאזן מלאי חודשי.

    Args:
        inventory: מתוך load_fuel_inventory().
        fuel_purchases_per_month: סה"כ ליטרים שנקנו לפי חודש (מחשבשבת + פרשנות).
            אם אין מחיר לליטר ידוע, אפשר לחשב liters = amount / avg_price.
        fuel_usage_per_month: סה"כ ליטרים שדווחו בתדלוקים לפי solar.xlsx.

    Returns:
        DataFrame עם: month, opening_l, purchases_l, usage_l,
        expected_closing_l, actual_closing_l, variance_l, status.
    """
    cols = ["month", "opening_l", "purchases_l", "usage_l",
            "expected_closing_l", "actual_closing_l", "variance_l", "status"]
    if inventory.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for _, r in inventory.iterrows():
        month = r["month"]
        opening = float(r["opening_l"]) if pd.notna(r["opening_l"]) else 0.0
        actual_closing = float(r["closing_l"]) if pd.notna(r["closing_l"]) else None
        purchases = float(fuel_purchases_per_month.get(month, 0))
        usage = float(fuel_usage_per_month.get(month, 0))
        expected_closing = opening + purchases - usage
        variance = (expected_closing - actual_closing) if actual_closing is not None else None
        if variance is None:
            status = "—"
        elif abs(variance) < 50:
            status = "OK"
        elif variance > 0:
            status = "חוסר"
        else:
            status = "עודף"
        rows.append({
            "month": month,
            "opening_l": opening,
            "purchases_l": purchases,
            "usage_l": usage,
            "expected_closing_l": round(expected_closing, 1),
            "actual_closing_l": round(actual_closing, 1) if actual_closing is not None else None,
            "variance_l": round(variance, 1) if variance is not None else None,
            "status": status,
        })
    return pd.DataFrame(rows, columns=cols)
