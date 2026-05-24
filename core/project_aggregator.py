"""אגרגציה של נתוני פרויקט לתצוגות שונות.

מקבל את ה-master.parquet ומחזיר תצוגות אגרגטיביות לפי:
    project / month / category / supplier / tool / כל שילוב.

הערה לסימן: בכל המאסטר amount > 0 = הוצאה, amount < 0 = הכנסה.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _expenses_only(df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר רק שורות הוצאה (amount חיובי)."""
    if df.empty:
        return df
    return df[df["amount"] > 0]


def _income_only(df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר רק שורות הכנסה (amount שלילי)."""
    if df.empty:
        return df
    return df[df["amount"] < 0]


def by_project(df: pd.DataFrame) -> pd.DataFrame:
    """סיכום הוצאות לפי פרויקט.

    Returns:
        DataFrame עם: project_id, project_name, total_expenses,
        total_income, balance, num_transactions.
    """
    cols = ["project_id", "project_name", "total_expenses",
            "total_income", "balance", "num_transactions"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    grouped = df.groupby(["project_id", "project_name"], dropna=False).agg(
        total_expenses=("amount", lambda s: s[s > 0].sum()),
        total_income=("amount", lambda s: -s[s < 0].sum()),
        num_transactions=("amount", "count"),
    ).reset_index()
    grouped["balance"] = grouped["total_income"] - grouped["total_expenses"]
    return grouped[cols].sort_values("total_expenses", ascending=False)


def by_month(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """סיכום הוצאות לפי חודש (אופציונלית לפרויקט בודד)."""
    cols = ["month", "total_expenses", "total_income", "balance", "num_transactions"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = df if project_id is None else df[df["project_id"] == project_id]
    if data.empty:
        return pd.DataFrame(columns=cols)

    grouped = data.groupby("month", dropna=False).agg(
        total_expenses=("amount", lambda s: s[s > 0].sum()),
        total_income=("amount", lambda s: -s[s < 0].sum()),
        num_transactions=("amount", "count"),
    ).reset_index()
    grouped["balance"] = grouped["total_income"] - grouped["total_expenses"]
    grouped = grouped.sort_values("month").reset_index(drop=True)
    return grouped[cols]


def by_category(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """סיכום הוצאות לפי קטגוריה."""
    cols = ["category", "total_amount", "num_transactions", "share_pct"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = df if project_id is None else df[df["project_id"] == project_id]
    data = _expenses_only(data)
    if data.empty:
        return pd.DataFrame(columns=cols)

    grouped = data.groupby("category", dropna=False).agg(
        total_amount=("amount", "sum"),
        num_transactions=("amount", "count"),
    ).reset_index()
    total = grouped["total_amount"].sum()
    grouped["share_pct"] = (grouped["total_amount"] / total * 100).round(1) if total else 0.0
    grouped = grouped.sort_values("total_amount", ascending=False).reset_index(drop=True)
    return grouped[cols]


def by_supplier(df: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """Top N ספקים לפי סה"כ חיובים, על פני כל הפרויקטים."""
    cols = ["supplier", "total_amount", "num_transactions",
            "num_projects", "first_date", "last_date"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = _expenses_only(df)
    data = data[data["supplier"].notna() & (data["supplier"] != "")]
    if data.empty:
        return pd.DataFrame(columns=cols)

    grouped = data.groupby("supplier", dropna=False).agg(
        total_amount=("amount", "sum"),
        num_transactions=("amount", "count"),
        num_projects=("project_id", "nunique"),
        first_date=("date", "min"),
        last_date=("date", "max"),
    ).reset_index()
    grouped = grouped.sort_values("total_amount", ascending=False).head(top_n).reset_index(drop=True)
    return grouped[cols]


def supplier_month_matrix(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """מטריצת ספק × חודש (pivot)."""
    if df.empty:
        return pd.DataFrame()

    data = _expenses_only(df)
    data = data[data["supplier"].notna() & (data["supplier"] != "")]
    if data.empty:
        return pd.DataFrame()

    top_suppliers = (
        data.groupby("supplier")["amount"].sum()
            .sort_values(ascending=False)
            .head(top_n)
            .index
    )
    data = data[data["supplier"].isin(top_suppliers)]
    pivot = data.pivot_table(
        index="supplier", columns="month", values="amount",
        aggfunc="sum", fill_value=0,
    )
    pivot = pivot.reindex(top_suppliers)
    pivot["סה\"כ"] = pivot.sum(axis=1)
    return pivot.sort_values("סה\"כ", ascending=False)


def category_month_matrix(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """מטריצת קטגוריה × חודש (pivot)."""
    if df.empty:
        return pd.DataFrame()

    data = df if project_id is None else df[df["project_id"] == project_id]
    data = _expenses_only(data)
    if data.empty:
        return pd.DataFrame()

    pivot = data.pivot_table(
        index="category", columns="month", values="amount",
        aggfunc="sum", fill_value=0,
    )
    pivot["סה\"כ"] = pivot.sum(axis=1)
    return pivot.sort_values("סה\"כ", ascending=False)
