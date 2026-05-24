"""שכבת שאילתות AI גבוהה-רמה על נתוני הביקורת.

עטיפה דקה מעל ai_tools.py שמכינה context מהדאטה לפני שליחה.
"""
from __future__ import annotations

import logging

import pandas as pd

from ai_tools import ask_ai_about_data, detect_issues_with_ai, summarize_month
from core import analytics

logger = logging.getLogger(__name__)


def _build_context(df: pd.DataFrame, project_id: str | None) -> str:
    """בונה מחרוזת הקשר אוטומטית: KPIs + סכמה."""
    if df.empty:
        return "אין נתונים זמינים."

    expenses = analytics.kpi_total_expenses(df, project_id)
    income = analytics.kpi_total_income(df, project_id)
    balance = analytics.kpi_balance(df, project_id)
    scope_txt = f"פרויקט: {project_id}" if project_id else f"כל הפרויקטים ({df['project_id'].nunique()})"

    months = sorted(df["month"].dropna().unique()) if "month" in df.columns else []
    period_txt = f"תקופה: {months[0]} עד {months[-1]}" if months else ""

    return (
        f"{scope_txt}\n"
        f"{period_txt}\n"
        f"סה\"כ הוצאות: {expenses:,.0f} ש\"ח\n"
        f"סה\"כ הכנסות: {income:,.0f} ש\"ח\n"
        f"יתרה: {balance:,.0f} ש\"ח\n"
        f"מס' תנועות: {len(df):,}\n"
        f"\nסכמת הטבלה: {', '.join(df.columns)}"
    )


def ask_with_context(
    df: pd.DataFrame,
    question: str,
    project_id: str | None = None,
) -> str:
    """שואל את ה-AI שאלה חופשית עם הקשר אוטומטי (KPIs + סכמה)."""
    context = _build_context(df, project_id)
    data = df if project_id is None else df[df["project_id"] == project_id]
    return ask_ai_about_data(data, question, context=context)


def get_audit_insights(df_anomalies: pd.DataFrame) -> list[dict]:
    """שולח את טבלת החריגות ל-AI לזיהוי דפוסים נוספים."""
    if df_anomalies.empty:
        return []
    return detect_issues_with_ai(df_anomalies)


def project_monthly_summary(df: pd.DataFrame, project_id: str, month: str) -> str:
    """מייצר סיכום AI לחודש בפרויקט בודד."""
    data = df[(df["project_id"] == project_id) & (df["month"] == month)]
    if data.empty:
        return f"אין נתונים לפרויקט {project_id} בחודש {month}."

    project_name = data["project_name"].iloc[0] if "project_name" in data.columns else project_id
    return summarize_month(data, project_name, month)
