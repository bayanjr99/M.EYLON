"""חישובי KPI, Top-N, מגמות - הזנת הדשבורד.

לא שומר state. כל פונקציה מקבלת df ומחזירה ערך/דאטה-פריים.

קונבנציית הסימן: amount > 0 = הוצאה, amount < 0 = הכנסה.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _scope(df: pd.DataFrame, project_id: str | None) -> pd.DataFrame:
    """מצמצם לפרויקט בודד אם נמסר project_id."""
    if df.empty or project_id is None:
        return df
    return df[df["project_id"] == project_id]


def kpi_total_expenses(df: pd.DataFrame, project_id: str | None = None) -> float:
    """סה"כ הוצאות (amount חיובי). אופציונלית לפרויקט בודד."""
    data = _scope(df, project_id)
    if data.empty:
        return 0.0
    return float(data.loc[data["amount"] > 0, "amount"].sum())


def kpi_total_income(df: pd.DataFrame, project_id: str | None = None) -> float:
    """סה"כ הכנסות (amount שלילי, מוחזר כערך מוחלט חיובי)."""
    data = _scope(df, project_id)
    if data.empty:
        return 0.0
    return float(-data.loc[data["amount"] < 0, "amount"].sum())


def kpi_balance(df: pd.DataFrame, project_id: str | None = None) -> float:
    """יתרה = הכנסות - הוצאות."""
    return kpi_total_income(df, project_id) - kpi_total_expenses(df, project_id)


def kpi_active_projects(df: pd.DataFrame) -> int:
    """מספר פרויקטים עם תנועות (project_id ייחודיים)."""
    if df.empty or "project_id" not in df.columns:
        return 0
    return int(df["project_id"].nunique())


def monthly_trend(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """מגמה חודשית: month, total_expenses, total_income, balance.

    הכנסות = רק מחשבונות הכנסה (927/951/7367 או category='הכנסות').
    הוצאות = amount>0 מחשבונות שאינם הכנסה.
    """
    cols = ["month", "total_expenses", "total_income", "balance"]
    data = _scope(df, project_id)
    if data.empty or "month" not in data.columns:
        return pd.DataFrame(columns=cols)

    from core.chashbashevet_loader import INCOME_ACCOUNTS
    chash = data[data["source"] == "chashbashevet"] if "source" in data.columns else data
    if chash.empty:
        return pd.DataFrame(columns=cols)

    income_mask = (
        chash["account_num"].isin(INCOME_ACCOUNTS) if "account_num" in chash.columns else False
    )
    if "category" in chash.columns:
        income_mask = income_mask | (chash["category"] == "הכנסות")
    chash = chash.assign(
        _is_income=income_mask,
        _income_amount=(-chash["amount"]).where(income_mask, 0),
        _expense_amount=chash["amount"].where(~income_mask & (chash["amount"] > 0), 0),
    )
    grouped = chash.groupby("month", dropna=False).agg(
        total_income=("_income_amount", "sum"),
        total_expenses=("_expense_amount", "sum"),
    ).reset_index()
    grouped["balance"] = grouped["total_income"] - grouped["total_expenses"]
    return grouped.sort_values("month").reset_index(drop=True)[cols]


def top_anomalies(df_anomalies: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Top N חריגות לפי estimated_impact_nis."""
    if df_anomalies.empty:
        return df_anomalies
    sort_col = "estimated_impact_nis" if "estimated_impact_nis" in df_anomalies.columns else None
    if sort_col is None:
        return df_anomalies.head(n)
    return df_anomalies.sort_values(sort_col, ascending=False).head(n).reset_index(drop=True)
