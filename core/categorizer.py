"""סיווג חשבונות חשבשבת לקטגוריות עסקיות.

טוען את data/category_mapping.xlsx ומחזיר קטגוריה לכל חשבון.

סדר ההתאמה:
    1. account_num — exact match לפי מספר חשבון
    2. name_keyword — substring match על account_name, לפי priority
    3. range fallback — לפי מספר חשבון (טווח חשבונאי)
    4. "אחר"

מבנה category_mapping.xlsx:
    priority | account_num | name_keyword | category | subcategory
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "category_mapping.xlsx"


def _classify_by_range(account_num: int) -> tuple[str, str]:
    """סיווג ברירת מחדל לחשבונות שלא במיפוי."""
    if 7430 <= account_num <= 7440:
        return ("הוצאות תפעוליות", "")
    if 7400 <= account_num <= 7499:
        return ("הוצאות פרויקט", "")
    if 7000 <= account_num <= 7399:
        return ("הוצאות שכר/כלליות", "")
    return ("אחר", "")


@lru_cache(maxsize=1)
def load_category_mapping(mapping_path: str = str(DEFAULT_MAPPING_PATH)) -> pd.DataFrame:
    """טוען את קובץ המיפוי. ממוטמן (lru_cache).

    Returns DataFrame עם עמודות: priority, account_num, name_keyword, category, subcategory.
    מסונן ל-rules תקפים (לפחות אחד מ-account_num/name_keyword חייב להיות מלא).
    """
    path = Path(mapping_path)
    cols = ["priority", "account_num", "name_keyword", "category", "subcategory"]
    if not path.exists():
        logger.warning("category_mapping.xlsx not found at %s", path)
        return pd.DataFrame(columns=cols)

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read category_mapping: %s", e)
        return pd.DataFrame(columns=cols)

    # סכמה לאחור-תאימה - אם אין priority, ברירת מחדל 50
    if "priority" not in df.columns:
        df["priority"] = 50
    if "name_keyword" not in df.columns:
        df["name_keyword"] = ""

    df["account_num"] = pd.to_numeric(df["account_num"], errors="coerce").astype("Int64")
    df["name_keyword"] = df["name_keyword"].fillna("").astype(str).str.strip()
    df["category"] = df["category"].fillna("אחר").astype(str)
    df["subcategory"] = df.get("subcategory", "").fillna("").astype(str)
    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(50).astype(int)

    # סנן rules ריקים
    valid = df[df["account_num"].notna() | (df["name_keyword"] != "")]
    return valid.sort_values("priority").reset_index(drop=True)


def categorize(account_num: int, account_name: str = "") -> tuple[str, str]:
    """מחזיר (category, subcategory) לחשבון נתון.

    סדר: exact account_num → keyword on account_name (לפי priority) → range fallback.
    """
    if account_num is None:
        return ("אחר", "")
    try:
        acct = int(account_num)
    except (TypeError, ValueError):
        return ("אחר", "")

    mapping = load_category_mapping()
    name_l = (account_name or "").lower()

    # שלב 1: exact account_num match
    if not mapping.empty:
        exact = mapping[mapping["account_num"] == acct]
        if not exact.empty:
            r = exact.iloc[0]
            return (r["category"], r["subcategory"])

    # שלב 2: keyword match (כבר ממוין לפי priority)
    if name_l:
        for _, r in mapping[mapping["name_keyword"] != ""].iterrows():
            kw = r["name_keyword"].lower()
            if kw and kw in name_l:
                return (r["category"], r["subcategory"])

    # שלב 3: range fallback
    return _classify_by_range(acct)


def categorize_dataframe(df: pd.DataFrame, account_col: str = "account_num",
                         name_col: str = "account_name") -> pd.DataFrame:
    """מוסיף עמודות category + subcategory ל-DataFrame קיים.

    משתמש ב-categorize() שורה-שורה (יחסית יקר, אבל פשוט וברור).
    לדאטה גדול אפשר לשפר ע"י vectorization של exact-match, אבל לא קריטי כרגע.
    """
    if df.empty or account_col not in df.columns:
        df = df.copy()
        df["category"] = ""
        df["subcategory"] = ""
        return df

    df = df.copy()
    name_series = df[name_col] if name_col in df.columns else pd.Series([""] * len(df), index=df.index)
    results = [
        categorize(row_num, row_name)
        for row_num, row_name in zip(df[account_col], name_series)
    ]
    df["category"] = [c for c, _ in results]
    df["subcategory"] = [s for _, s in results]
    return df


def report_unmapped(df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר דוח חשבונות שלא קיבלו קטגוריה מפורשת.

    כלומר נפלו לטווח (הוצאות תפעוליות / פרויקט / שכר / אחר).
    שימושי כדי לראות מה צריך להוסיף ל-category_mapping.xlsx.
    """
    range_fallback_cats = {"הוצאות תפעוליות", "הוצאות פרויקט",
                           "הוצאות שכר/כלליות", "אחר"}
    if df.empty or "category" not in df.columns:
        return pd.DataFrame(columns=["account_num", "account_name", "category",
                                      "total_amount", "num_transactions"])

    unmapped = df[df["category"].isin(range_fallback_cats)]
    if unmapped.empty:
        return pd.DataFrame(columns=["account_num", "account_name", "category",
                                      "total_amount", "num_transactions"])

    agg = unmapped.groupby(["account_num", "account_name", "category"], dropna=False).agg(
        total_amount=("amount", lambda s: float(s.abs().sum())),
        num_transactions=("amount", "size"),
    ).reset_index().sort_values("total_amount", ascending=False)
    return agg


def save_unmapped_report(df: pd.DataFrame, out_path: str | Path | None = None) -> Path:
    """שומר את דוח הלא-ממופים ל-output/reports/unmapped_accounts.xlsx."""
    if out_path is None:
        out_path = (Path(__file__).resolve().parent.parent /
                    "output" / "reports" / "unmapped_accounts.xlsx")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = report_unmapped(df)
    report.to_excel(out_path, index=False, engine="openpyxl")
    logger.info("Saved unmapped report (%d rows) to %s", len(report), out_path)
    return out_path
