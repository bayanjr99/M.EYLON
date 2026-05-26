"""רווחיות לפי כלי ולפי ספק + תחזית סוף פרויקט.

API:
    tool_profitability(df, project_id) → DataFrame
    supplier_profitability(df, project_id, anomaly_threshold=2.0) → DataFrame
    project_forecast(df, project_id) → dict

עקרון: כל החישובים זורמים דרך real_income_mask + fuel_assignments,
כך שמסקנות עקביות עם שאר המסכים.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ── רווחיות לפי כלי ───────────────────────────────────────

def tool_profitability(df_master: pd.DataFrame,
                         project_id: str) -> pd.DataFrame:
    """DataFrame של רווחיות לכל כלי.

    עמודות: license_num, tool_name, total_fuel_cost, total_liters,
            total_hours, n_months_active, lph, cost_per_hour, anomalies.

    fuel_cost כולל:
      - תדלוקים מ-solar.xlsx (לפי avg_price ⨯ liters)
      - שיוכים ידניים מ-chashbashevet (סכום מלא)
    """
    if df_master.empty:
        return pd.DataFrame()
    project_df = df_master[df_master["project_id"] == project_id] \
        if "project_id" in df_master.columns else df_master
    if project_df.empty:
        return pd.DataFrame()

    from pipeline import _load_tools_registry
    from core import fuel_assignments
    tools_reg = _load_tools_registry()

    solar = project_df[project_df["source"] == "solar"] \
        if "source" in project_df.columns else project_df.iloc[0:0]
    hours = project_df[project_df["source"] == "hours"] \
        if "source" in project_df.columns else project_df.iloc[0:0]
    chash = project_df[project_df["source"] == "chashbashevet"] \
        if "source" in project_df.columns else project_df.iloc[0:0]

    # מחיר ממוצע לליטר (chashbashevet fuel total ÷ solar total liters)
    from ui.pages.project_detail import KEYWORD_CATEGORIES, _filter_by_keywords
    try:
        fuel_chash = _filter_by_keywords(chash, KEYWORD_CATEGORIES["fuel"])
    except Exception:
        fuel_chash = chash[chash.get("main_category", "") == "דלק ואנרגיה"] \
            if "main_category" in chash.columns else chash.iloc[0:0]
    if "amount" in fuel_chash.columns:
        fuel_chash = fuel_chash[fuel_chash["amount"] > 0]
    total_fuel_cost = float(fuel_chash["amount"].sum()) if not fuel_chash.empty else 0
    total_liters_all = float(solar["liters"].sum()) \
        if "liters" in solar.columns and not solar.empty else 0
    avg_price = total_fuel_cost / total_liters_all if total_liters_all > 0 else 0

    # אגרגציה
    rows = []
    license_set: set[int] = set()
    if not solar.empty and "license_num" in solar.columns:
        license_set.update(solar["license_num"].dropna().astype(int).tolist())
    if not hours.empty and "license_num" in hours.columns:
        license_set.update(hours["license_num"].dropna().astype(int).tolist())

    # licenses ששויכו ידנית
    manual = fuel_assignments.fuel_cost_per_license(project_id, project_df)
    if not manual.empty:
        license_set.update(manual["license_num"].astype(int).tolist())

    if not license_set:
        return pd.DataFrame()

    tools_idx = tools_reg.set_index("license_num", drop=False) \
        if not tools_reg.empty and "license_num" in tools_reg.columns \
        else pd.DataFrame()
    manual_idx = manual.set_index("license_num", drop=False) \
        if not manual.empty else pd.DataFrame()

    for lic in license_set:
        # ליטרים ושעות
        liters = float(solar[solar["license_num"] == lic]["liters"].sum()) \
            if not solar.empty else 0
        work_hours = float(hours[hours["license_num"] == lic]["work_hours"].sum()) \
            if not hours.empty else 0
        # חודשים פעילים
        active_months = set()
        if not solar.empty:
            active_months.update(solar[solar["license_num"] == lic]
                                  ["month"].dropna().unique())
        if not hours.empty:
            active_months.update(hours[hours["license_num"] == lic]
                                  ["month"].dropna().unique())

        # שם
        tool_name = ""
        if not tools_idx.empty and lic in tools_idx.index:
            tool_name = str(tools_idx.loc[lic].get("tool_name", "") or "")

        # עלות דלק = avg_price × ליטרים + שיוכים ידניים
        cost_from_liters = liters * avg_price
        cost_manual = float(manual_idx.loc[lic]["assigned_fuel_cost"]) \
            if not manual_idx.empty and lic in manual_idx.index else 0
        total_cost = cost_from_liters + cost_manual

        # מטריקות נגזרות
        lph = round(liters / work_hours, 2) if work_hours > 0 else 0
        cost_per_hour = round(total_cost / work_hours, 1) if work_hours > 0 else 0

        # אזהרות
        anomalies = []
        if liters > 0 and work_hours == 0:
            anomalies.append("דלק ללא שעות")
        if work_hours > 0 and liters == 0 and cost_manual == 0:
            anomalies.append("שעות ללא דלק")
        if not tools_idx.empty and lic in tools_idx.index:
            norm_high = tools_idx.loc[lic].get("norm_high")
            if pd.notna(norm_high) and norm_high and lph > float(norm_high) * 1.15:
                anomalies.append("חריגה מתקן")

        rows.append({
            "license_num":     lic,
            "tool_name":       tool_name,
            "total_fuel_cost": round(total_cost, 0),
            "total_liters":    round(liters, 0),
            "total_hours":     round(work_hours, 1),
            "n_months_active": len(active_months),
            "lph":             lph,
            "cost_per_hour":   cost_per_hour,
            "manual_cost":     round(cost_manual, 0),
            "anomalies":       ", ".join(anomalies) if anomalies else "✓",
        })

    return pd.DataFrame(rows).sort_values("total_fuel_cost", ascending=False) \
        .reset_index(drop=True)


# ── רווחיות לפי ספק (+ זיהוי חריגים) ─────────────────────

def supplier_profitability(df_master: pd.DataFrame,
                              project_id: str,
                              anomaly_z: float = 2.0) -> pd.DataFrame:
    """DataFrame של ניתוח ספקים.

    עמודות: supplier, total_spend, n_invoices, n_months_active,
            monthly_avg, last_month_amount, is_anomaly, is_new.

    is_anomaly: True אם הסכום בחודש האחרון חורג ב-z*std מהממוצע ההיסטורי.
    is_new: True אם הספק מופיע רק בחודש האחרון.
    """
    if df_master.empty:
        return pd.DataFrame()
    project_df = df_master[df_master["project_id"] == project_id] \
        if "project_id" in df_master.columns else df_master
    if project_df.empty:
        return pd.DataFrame()

    chash = project_df[project_df["source"] == "chashbashevet"] \
        if "source" in project_df.columns else project_df
    if chash.empty or "supplier" not in chash.columns:
        return pd.DataFrame()
    exp = chash[chash["amount"] > 0]
    exp = exp[exp["supplier"].fillna("").astype(str).str.strip() != ""]
    if exp.empty:
        return pd.DataFrame()

    months_sorted = sorted(exp["month"].dropna().unique()) \
        if "month" in exp.columns else []
    last_month = months_sorted[-1] if months_sorted else None

    rows = []
    for sup, grp in exp.groupby("supplier"):
        total = float(grp["amount"].sum())
        n_inv = int(len(grp))
        months = grp["month"].dropna().unique() if "month" in grp.columns else []
        n_months = len(months)
        monthly_avg = total / n_months if n_months > 0 else 0
        last_amt = 0
        is_anomaly = False
        is_new = False
        if last_month and "month" in grp.columns:
            last_amt = float(grp[grp["month"] == last_month]["amount"].sum())
            if n_months == 1 and last_month in months:
                is_new = True
            # zscore אם n_months >= 3
            if n_months >= 3:
                hist = grp[grp["month"] != last_month] \
                    .groupby("month")["amount"].sum()
                if len(hist) >= 2 and hist.std() > 0:
                    z = (last_amt - hist.mean()) / hist.std()
                    if abs(z) > anomaly_z:
                        is_anomaly = True

        rows.append({
            "supplier":          sup,
            "total_spend":       round(total, 0),
            "n_invoices":        n_inv,
            "n_months_active":   n_months,
            "monthly_avg":       round(monthly_avg, 0),
            "last_month_amount": round(last_amt, 0),
            "is_anomaly":        is_anomaly,
            "is_new":            is_new,
        })

    return pd.DataFrame(rows).sort_values("total_spend", ascending=False) \
        .reset_index(drop=True)


# ── תחזית סוף פרויקט ─────────────────────────────────────

def project_forecast(df_master: pd.DataFrame, project_id: str,
                       months_ahead: int = 6) -> dict:
    """מחזיר תחזית פשוטה ל-X חודשים קדימה לפי ממוצע חודשי.

    Returns dict עם:
        projected_revenue, projected_expenses, projected_profit,
        projected_profit_pct, risk_level (low/medium/high),
        avg_monthly_revenue, avg_monthly_expenses,
        n_months_history, conclusion (str).
    """
    from core.project_aggregator import project_summary
    summary = project_summary(df_master, project_id)
    n_months = len(summary.get("months", []) or [])
    revenue = summary.get("revenue", 0)
    expenses = summary.get("expenses", 0)

    if n_months == 0:
        return {
            "n_months_history": 0,
            "projected_revenue": 0, "projected_expenses": 0,
            "projected_profit": 0, "projected_profit_pct": 0,
            "risk_level": "unknown",
            "conclusion": "אין נתונים היסטוריים לתחזית.",
            "avg_monthly_revenue": 0, "avg_monthly_expenses": 0,
        }

    avg_rev = revenue / n_months
    avg_exp = expenses / n_months
    proj_rev = revenue + avg_rev * months_ahead
    proj_exp = expenses + avg_exp * months_ahead
    proj_profit = proj_rev - proj_exp
    proj_pct = (proj_profit / proj_rev * 100) if proj_rev > 0 else 0

    # רמת סיכון
    if proj_profit < 0:
        risk = "high"
        conclusion = (f"🚨 הפרויקט צפוי לסיים בהפסד של "
                       f"₪{abs(proj_profit):,.0f}. דורש שינוי דחוף.")
    elif proj_pct < 5:
        risk = "medium"
        conclusion = (f"⚠️ רווחיות צפויה נמוכה ({proj_pct:.1f}%). "
                       "מומלץ לבחון אופטימיזציה של הוצאות.")
    elif proj_pct < 15:
        risk = "low"
        conclusion = (f"✅ הפרויקט בכיוון חיובי. רווחיות צפויה: "
                       f"{proj_pct:.1f}%.")
    else:
        risk = "low"
        conclusion = (f"🎯 רווחיות גבוהה צפויה: {proj_pct:.1f}%. "
                       "ביצוע מצוין.")

    return {
        "n_months_history": n_months,
        "projected_revenue": round(proj_rev, 0),
        "projected_expenses": round(proj_exp, 0),
        "projected_profit": round(proj_profit, 0),
        "projected_profit_pct": round(proj_pct, 1),
        "risk_level": risk,
        "conclusion": conclusion,
        "avg_monthly_revenue": round(avg_rev, 0),
        "avg_monthly_expenses": round(avg_exp, 0),
    }
