"""סיווג חשבונות חשבשבת לקטגוריות עסקיות.

טוען את data/category_mapping.xlsx ומחזיר קטגוריה לכל מספר חשבון.
לחשבונות שלא במיפוי - סיווג לפי טווח (account_num).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DEFAULT_MAPPING_PATH = Path("data/category_mapping.xlsx")


def _classify_by_range(account_num: int) -> tuple[str, str]:
    """סיווג ברירת מחדל לחשבונות שלא במיפוי.

    Returns:
        (category, subcategory)
    """
    if 7430 <= account_num <= 7440:
        return ("הוצאות תפעוליות", "")
    if 7400 <= account_num <= 7499:
        return ("הוצאות פרויקט", "")
    if 7000 <= account_num <= 7399:
        return ("הוצאות שכר/כלליות", "")
    return ("אחר", "")


@lru_cache(maxsize=1)
def load_category_mapping(mapping_path: str = str(DEFAULT_MAPPING_PATH)) -> pd.DataFrame:
    """טוען את קובץ המיפוי. ממוטמן (lru_cache) כדי לחסוך קריאות חוזרות."""
    path = Path(mapping_path)
    if not path.exists():
        logger.warning("category_mapping.xlsx not found at %s", path)
        return pd.DataFrame(columns=["account_num", "account_name", "category", "subcategory"])

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read category_mapping: %s", e)
        return pd.DataFrame(columns=["account_num", "account_name", "category", "subcategory"])

    df["account_num"] = pd.to_numeric(df["account_num"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["account_num"])
    df["subcategory"] = df.get("subcategory", "").fillna("")
    df["category"] = df.get("category", "").fillna("אחר")
    return df.reset_index(drop=True)


def categorize(account_num: int, account_name: str = "") -> tuple[str, str]:
    """מחזיר (category, subcategory) לחשבון נתון.

    קודם מחפש במיפוי, אחרת נופל לסיווג לפי טווח.
    """
    if account_num is None:
        return ("אחר", "")

    try:
        acct_num = int(account_num)
    except (TypeError, ValueError):
        return ("אחר", "")

    mapping = load_category_mapping()
    if not mapping.empty:
        hit = mapping[mapping["account_num"] == acct_num]
        if not hit.empty:
            row = hit.iloc[0]
            return (str(row["category"]), str(row.get("subcategory", "") or ""))

    return _classify_by_range(acct_num)


def categorize_dataframe(df: pd.DataFrame, account_col: str = "account_num") -> pd.DataFrame:
    """מוסיף עמודות category + subcategory ל-DataFrame קיים.

    שימושי לאחר טעינת חשבשבת - מוסיף את הסיווג בבת אחת.
    """
    if df.empty or account_col not in df.columns:
        df = df.copy()
        df["category"] = ""
        df["subcategory"] = ""
        return df

    mapping = load_category_mapping()
    df = df.copy()

    # החל קטגוריות לפי המיפוי
    if not mapping.empty:
        m = mapping[["account_num", "category", "subcategory"]].drop_duplicates("account_num")
        df = df.merge(m, how="left", left_on=account_col, right_on="account_num", suffixes=("", "_map"))
        if "account_num_map" in df.columns:
            df = df.drop(columns=["account_num_map"])

    # fallback לפי טווח לחשבונות לא ממופים
    missing = df["category"].isna() | (df["category"] == "")
    if missing.any():
        fills = df.loc[missing, account_col].apply(
            lambda x: _classify_by_range(int(x)) if pd.notna(x) else ("אחר", "")
        )
        df.loc[missing, "category"] = [c for c, _ in fills]
        df.loc[missing, "subcategory"] = [s for _, s in fills]

    df["category"] = df["category"].fillna("אחר")
    df["subcategory"] = df["subcategory"].fillna("")
    return df
