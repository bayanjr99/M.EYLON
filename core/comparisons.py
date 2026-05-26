"""השוואות — בין חודשים ובין פרויקטים.

API:
    compare_months(df, project_id, months) → DataFrame
    compare_projects(df_master, project_ids) → DataFrame

כל ההשוואות מחזירות KPI לפי קבוצה + עמודות שינוי באחוזים.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _kpis_for_scope(df: pd.DataFrame) -> dict:
    """מחשב הכנסות / הוצאות / רווח / דלק / שעות / חריגות עבור scope."""
    from core.chashbashevet_loader import real_income_mask
    out = {
        "revenue": 0, "expenses": 0, "profit": 0,
        "fuel_cost": 0, "fuel_liters": 0, "work_hours": 0,
        "num_tx": 0, "num_suppliers": 0,
    }
    if df.empty:
        return out

    if "source" in df.columns:
        chash = df[df["source"] == "chashbashevet"]
        solar = df[df["source"] == "solar"]
        hours = df[df["source"] == "hours"]
    else:
        chash, solar, hours = df, df.iloc[0:0], df.iloc[0:0]

    if not chash.empty:
        out["num_tx"] = int(len(chash))
        income_mask = real_income_mask(chash)
        out["revenue"] = float(-chash[income_mask]["amount"].sum()) \
            if income_mask.any() else 0
        expense_mask = ~income_mask & (chash["amount"] > 0)
        out["expenses"] = float(chash[expense_mask]["amount"].sum()) \
            if expense_mask.any() else 0
        out["profit"] = out["revenue"] - out["expenses"]
        if "main_category" in chash.columns:
            fuel = chash[chash["main_category"] == "דלק ואנרגיה"]
            if not fuel.empty:
                out["fuel_cost"] = float(fuel[fuel["amount"] > 0]["amount"].sum())
        if "supplier" in chash.columns:
            out["num_suppliers"] = int(
                chash["supplier"].fillna("").astype(str)
                    .replace("", pd.NA).dropna().nunique()
            )

    if not solar.empty and "liters" in solar.columns:
        out["fuel_liters"] = float(solar["liters"].sum())
    if not hours.empty and "work_hours" in hours.columns:
        out["work_hours"] = float(hours["work_hours"].sum())

    return out


def compare_months(df: pd.DataFrame, project_id: str,
                    months: list[str]) -> pd.DataFrame:
    """מחזיר DataFrame של KPIs לפי חודש + עמודת שינוי מהחודש הקודם."""
    if df.empty or not months:
        return pd.DataFrame()
    project_df = df[df["project_id"] == project_id] \
        if "project_id" in df.columns else df

    rows = []
    prev_kpis = None
    for m in months:
        scope = project_df[project_df["month"] == m] \
            if "month" in project_df.columns else project_df.iloc[0:0]
        kpi = _kpis_for_scope(scope)
        kpi["month"] = m
        if prev_kpis is not None:
            kpi["change_revenue_pct"] = _pct_change(prev_kpis["revenue"], kpi["revenue"])
            kpi["change_expenses_pct"] = _pct_change(prev_kpis["expenses"], kpi["expenses"])
            kpi["change_profit_pct"] = _pct_change(prev_kpis["profit"], kpi["profit"])
            kpi["change_fuel_pct"] = _pct_change(prev_kpis["fuel_cost"], kpi["fuel_cost"])
        else:
            for c in ("change_revenue_pct", "change_expenses_pct",
                       "change_profit_pct", "change_fuel_pct"):
                kpi[c] = None
        rows.append(kpi)
        prev_kpis = kpi

    cols = ["month", "revenue", "change_revenue_pct",
            "expenses", "change_expenses_pct",
            "profit", "change_profit_pct",
            "fuel_cost", "change_fuel_pct",
            "fuel_liters", "work_hours", "num_tx", "num_suppliers"]
    return pd.DataFrame(rows)[cols]


def compare_projects(df_master: pd.DataFrame,
                       project_ids: list[str] | None = None) -> pd.DataFrame:
    """מחזיר DataFrame של KPIs לפי פרויקט.

    אם project_ids=None — משווה את כל הפרויקטים במאסטר.
    """
    if df_master.empty or "project_id" not in df_master.columns:
        return pd.DataFrame()
    if project_ids is None:
        project_ids = sorted(df_master["project_id"].dropna().unique())

    from core.project_store import get_project_by_id, STATUS_HE
    rows = []
    for pid in project_ids:
        scope = df_master[df_master["project_id"] == pid]
        kpi = _kpis_for_scope(scope)
        proj = get_project_by_id(pid) or {}
        kpi["project_id"] = pid
        kpi["project_name"] = proj.get("project_name") or pid
        kpi["status"] = STATUS_HE.get(proj.get("status") or "active", "פעיל")
        kpi["profit_pct"] = (
            (kpi["profit"] / kpi["revenue"] * 100)
            if kpi["revenue"] > 0 else 0
        )
        rows.append(kpi)

    cols = ["project_id", "project_name", "status",
            "revenue", "expenses", "profit", "profit_pct",
            "fuel_cost", "fuel_liters", "work_hours",
            "num_tx", "num_suppliers"]
    df = pd.DataFrame(rows)[cols] if rows else pd.DataFrame(columns=cols)
    return df.sort_values("revenue", ascending=False).reset_index(drop=True)


def _pct_change(prev: float, curr: float) -> float | None:
    if not prev:
        return None
    return round((curr - prev) / abs(prev) * 100, 1)
