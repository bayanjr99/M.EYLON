"""טעינת דוח רכש פריטים (חשבוניות סולר ברמת פירוט) מחשבשבת.

מבנה הקובץ (Book1-style, פלט "דוח רכש לפי פריט"):
    שורות 0-1: כותרת חברה + כותרת דוח
    שורה 2: כותרות עמודות (header=2)
    מעמודה 3 (D) ואילך: רשומות פריט

עמודות עיקריות:
    מפתח פריט         = item key (108007 = סולר)
    שם פריט בתנועה    = item description (כולל לעיתים שיוך לרכב/אתר)
    מספר מסמך         = invoice number
    תאריך אסמכתא      = invoice date
    מפתח חשבון        = supplier account key
    שם חשבון במסמך    = supplier name
    כמות              = liters
    מחיר בתנועה       = ₪ per liter
    סה"כ בתנועה       = total ₪
    קוד מיון חשבון    = site/project code (743 = ראשון לציון)

הקובץ מכיל את כל החברה (כל האתרים) לאורך זמן.
הסינון לפרויקט נעשה לפי SITE_CODE_TO_PROJECT.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# מיפוי קוד מיון בחשבשבת → project_id במערכת
# (ניתן להרחיב כשנוסיף פרויקטים נוספים למערכת)
SITE_CODE_TO_PROJECT: dict[int, str] = {
    743: "rishon_letzion",
    # 730: "netanya", 717: "afe", 702: "office", 700: "...", etc.
}


COLUMN_MAP = {
    "מפתח פריט": "item_key",
    "שם פריט בתנועה": "item_description",
    "מספר מסמך": "invoice_num",
    "תאריך אסמכתא": "date",
    "מפתח חשבון": "supplier_account_key",
    "שם חשבון במסמך": "supplier",
    "כמות": "liters",
    "מחיר בתנועה": "price_per_liter",
    "סה\"כ בתנועה": "total_cost",
    "מזהה מלאי": "inventory_id",
    "קוד מיון חשבון הכנסות / הוצאות": "site_code",
}

OUTPUT_COLS = [
    "date", "invoice_num", "supplier", "liters", "price_per_liter",
    "total_cost", "site_code", "project_id", "item_description", "month",
]


def load_fuel_invoices(file_path: str | Path) -> pd.DataFrame:
    """טוען דוח רכש פריטים. מחזיר DataFrame מנורמל עם project_id."""
    path = Path(file_path)
    if not path.exists():
        logger.info("fuel_invoices file not found: %s", path)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        # header=2 כי שורות 0-1 הן כותרת
        df = pd.read_excel(path, header=2, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read fuel_invoices: %s", e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    # Rename, drop empty/summary rows
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})
    df = df.dropna(subset=["item_key"])

    # Convert types
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()]
    for c in ("liters", "price_per_liter", "total_cost"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["site_code"] = pd.to_numeric(df.get("site_code"), errors="coerce").astype("Int64")
    df["invoice_num"] = df["invoice_num"].astype(str).str.strip()
    df["month"] = df["date"].dt.strftime("%m-%Y")

    # Map site_code → project_id
    df["project_id"] = df["site_code"].map(
        lambda c: SITE_CODE_TO_PROJECT.get(int(c)) if pd.notna(c) else None
    )

    # Ensure all output cols
    for c in OUTPUT_COLS:
        if c not in df.columns:
            df[c] = None

    logger.info("Loaded %d fuel invoices from %s", len(df), path.name)
    return df[OUTPUT_COLS].reset_index(drop=True)


def filter_by_project(df: pd.DataFrame, project_id: str) -> pd.DataFrame:
    """מסנן את חשבוניות הסולר לפרויקט."""
    if df.empty:
        return df
    return df[df["project_id"] == project_id].reset_index(drop=True)


def summary_by_supplier(df: pd.DataFrame) -> pd.DataFrame:
    """סיכום: חשבוניות, ליטרים, סה"כ, ₪ ממוצע לליטר לכל ספק."""
    if df.empty:
        return pd.DataFrame(columns=["supplier", "invoices", "liters", "total_cost", "avg_price"])
    g = df.groupby("supplier").agg(
        invoices=("invoice_num", "count"),
        liters=("liters", "sum"),
        total_cost=("total_cost", "sum"),
    ).reset_index()
    g["avg_price"] = (g["total_cost"] / g["liters"]).round(2)
    g["liters"] = g["liters"].round(0)
    g["total_cost"] = g["total_cost"].round(0)
    return g.sort_values("total_cost", ascending=False)


def summary_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """סיכום חודשי: ליטרים, עלות, מחיר ממוצע."""
    if df.empty:
        return pd.DataFrame(columns=["month", "invoices", "liters", "total_cost", "avg_price"])
    g = df.groupby("month").agg(
        invoices=("invoice_num", "count"),
        liters=("liters", "sum"),
        total_cost=("total_cost", "sum"),
    ).reset_index()
    g["avg_price"] = (g["total_cost"] / g["liters"]).round(2)
    g["liters"] = g["liters"].round(0)
    g["total_cost"] = g["total_cost"].round(0)
    return g.sort_values("month")
