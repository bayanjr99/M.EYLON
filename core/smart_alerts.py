"""מנוע התראות חכמות לפרויקט.

מחזיר רשימה של התראות פתוחות לכל פרויקט. כל התראה כוללת:
    - severity:    "high" / "medium" / "low" / "info"
    - category:    "fuel" / "expense" / "supplier" / "income" / "tool"
    - title:       כותרת קצרה בעברית
    - body:        הסבר מפורט בעברית
    - amount:      סכום השפעה משוער (₪) או None
    - related:     dict עם metadata רלוונטי (license_num, supplier וכו')

עקרון: התראות מסונכרנות עם real_income_mask + main_category מהמאסטר;
לא ייצור דאטה חדשה — רק קורא מה שכבר נטען.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

SEVERITY_HE = {
    "high":   "גבוה",
    "medium": "בינוני",
    "low":    "נמוך",
    "info":   "מידע",
}

SEVERITY_COLOR = {
    "high":   "red",
    "medium": "amber",
    "low":    "blue",
    "info":   "blue",
}


def _alert(severity: str, category: str, title: str, body: str,
            amount: float | None = None, **related: Any) -> dict:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "body": body,
        "amount": amount,
        "related": related,
    }


# ── הבדיקות עצמן ───────────────────────────────────────────

def _check_project_in_loss(df: pd.DataFrame, project_id: str) -> list[dict]:
    """פרויקט בהפסד: profit < 0."""
    from core.project_aggregator import project_summary
    s = project_summary(df, project_id)
    if not s["has_data"]:
        return []
    if s["revenue"] == 0:
        return []
    if s["profit"] < 0:
        return [_alert(
            "high", "income", "פרויקט בהפסד",
            f"רווח שלילי של ₪{abs(s['profit']):,.0f} — "
            f"הוצאות (₪{s['expenses']:,.0f}) עולות על הכנסות "
            f"(₪{s['revenue']:,.0f}).",
            amount=s["profit"],
        )]
    return []


def _check_months_without_income(df: pd.DataFrame) -> list[dict]:
    """חודש שיש בו הוצאות אבל אפס הכנסות."""
    from core.chashbashevet_loader import real_income_mask
    if "source" not in df.columns or "month" not in df.columns:
        return []
    chash = df[df["source"] == "chashbashevet"]
    if chash.empty:
        return []
    inc_mask = real_income_mask(chash)
    out = []
    for month, grp in chash.groupby("month"):
        if not month:
            continue
        inc_grp = grp[inc_mask.loc[grp.index]]
        inc_total = -inc_grp["amount"].sum() if not inc_grp.empty else 0
        exp_grp = grp[~inc_mask.loc[grp.index] & (grp["amount"] > 0)]
        exp_total = exp_grp["amount"].sum() if not exp_grp.empty else 0
        if exp_total > 0 and inc_total == 0:
            out.append(_alert(
                "medium", "income",
                f"חודש {month} ללא הכנסות",
                f"בחודש {month} נרשמו הוצאות של ₪{exp_total:,.0f} "
                f"אך אפס הכנסות.",
                amount=exp_total, month=month,
            ))
    return out


def _check_duplicate_invoices(df: pd.DataFrame) -> list[dict]:
    """חשבונית כפולה: אותו ספק + סכום + חודש."""
    if "source" not in df.columns:
        return []
    chash = df[df["source"] == "chashbashevet"]
    if chash.empty or "supplier" not in chash.columns:
        return []
    exp = chash[chash["amount"] > 0]
    exp = exp[exp["supplier"].fillna("").astype(str).str.strip() != ""]
    if exp.empty:
        return []
    grouped = exp.groupby(["supplier", "amount", "month"],
                            dropna=False).size().reset_index(name="n")
    dups = grouped[grouped["n"] > 1]
    out = []
    for _, row in dups.head(20).iterrows():
        out.append(_alert(
            "medium", "expense",
            f"חשבונית כפולה אצל {row['supplier']}",
            f"ספק '{row['supplier']}' עם סכום ₪{row['amount']:,.0f} "
            f"נרשם {int(row['n'])} פעמים בחודש {row['month']}. "
            "ייתכן רישום כפול.",
            amount=float(row["amount"]) * (row["n"] - 1),
            supplier=row["supplier"], month=row["month"],
        ))
    return out


def _check_high_fuel_share(df: pd.DataFrame) -> list[dict]:
    """דלק כאחוז מההוצאות > 40%."""
    if "source" not in df.columns:
        return []
    chash = df[df["source"] == "chashbashevet"]
    if chash.empty or "amount" not in chash.columns:
        return []
    exp = chash[chash["amount"] > 0]
    if exp.empty:
        return []
    total = exp["amount"].sum()
    if total <= 0:
        return []
    if "main_category" in exp.columns:
        fuel = exp[exp["main_category"] == "דלק ואנרגיה"]
    elif "category" in exp.columns:
        fuel = exp[exp["category"].fillna("").str.contains("דלק|סולר", regex=True)]
    else:
        return []
    if fuel.empty:
        return []
    fuel_total = fuel["amount"].sum()
    pct = fuel_total / total * 100
    if pct > 40:
        sev = "high" if pct > 60 else "medium"
        return [_alert(
            sev, "fuel", f"דלק גבוה: {pct:.0f}% מההוצאות",
            f"הוצאות הדלק (₪{fuel_total:,.0f}) מהוות {pct:.0f}% "
            f"מסך ההוצאות (₪{total:,.0f}). "
            "מומלץ לבדוק שימוש חורג או נזילות.",
            amount=fuel_total,
        )]
    return []


def _check_tool_fuel_without_hours(df: pd.DataFrame) -> list[dict]:
    """כלי עם דלק אבל בלי שעות עבודה."""
    if "source" not in df.columns or "license_num" not in df.columns:
        return []
    solar = df[df["source"] == "solar"]
    hours = df[df["source"] == "hours"]
    if solar.empty:
        return []
    fueled = set(solar["license_num"].dropna().astype(int).tolist())
    worked = set(hours["license_num"].dropna().astype(int).tolist()) if not hours.empty else set()
    orphans = fueled - worked
    if not orphans:
        return []
    out = []
    for lic in list(orphans)[:5]:
        lic_solar = solar[solar["license_num"] == lic]
        liters = lic_solar["liters"].sum() if "liters" in lic_solar.columns else 0
        tool_name = ""
        if "tool_name" in lic_solar.columns:
            names = lic_solar["tool_name"].dropna()
            tool_name = names.iloc[0] if not names.empty else ""
        out.append(_alert(
            "medium", "tool", f"כלי {lic} תודלק אך לא דווחו שעות",
            f"רכב/כלי {lic} ({tool_name or 'ללא שם'}) קיבל {liters:,.0f} ל' דלק "
            "אבל לא רשומות לו שעות עבודה. "
            "ייתכן בזבוז דלק או רישום חסר.",
            amount=None, license_num=lic,
        ))
    return out


def _check_tool_hours_without_fuel(df: pd.DataFrame) -> list[dict]:
    """כלי עם שעות עבודה אבל בלי דלק."""
    if "source" not in df.columns or "license_num" not in df.columns:
        return []
    solar = df[df["source"] == "solar"]
    hours = df[df["source"] == "hours"]
    if hours.empty:
        return []
    fueled = set(solar["license_num"].dropna().astype(int).tolist()) if not solar.empty else set()
    worked = set(hours["license_num"].dropna().astype(int).tolist())
    no_fuel = worked - fueled
    if not no_fuel:
        return []
    out = []
    for lic in list(no_fuel)[:5]:
        lic_h = hours[hours["license_num"] == lic]
        work_h = lic_h["work_hours"].sum() if "work_hours" in lic_h.columns else 0
        tool_name = ""
        if "tool_name" in lic_h.columns:
            names = lic_h["tool_name"].dropna()
            tool_name = names.iloc[0] if not names.empty else ""
        out.append(_alert(
            "low", "tool", f"כלי {lic} עבד אך לא נרשם תדלוק",
            f"רכב/כלי {lic} ({tool_name or 'ללא שם'}) עבד {work_h:.0f} שעות "
            "ללא רישום תדלוק. "
            "ייתכן רכב חשמלי או תדלוק חיצוני שלא נכלל.",
            amount=None, license_num=lic,
        ))
    return out


def _check_new_suppliers(df: pd.DataFrame) -> list[dict]:
    """ספק שמופיע רק בחודש האחרון (חשד לחדש)."""
    if "source" not in df.columns:
        return []
    chash = df[df["source"] == "chashbashevet"]
    if chash.empty or "supplier" not in chash.columns or "month" not in chash.columns:
        return []
    exp = chash[chash["amount"] > 0]
    exp = exp[exp["supplier"].fillna("").astype(str).str.strip() != ""]
    if exp.empty:
        return []
    months = sorted(exp["month"].dropna().unique())
    if len(months) < 2:
        return []
    last_month = months[-1]
    last_sups = set(exp[exp["month"] == last_month]["supplier"].dropna())
    prev_sups = set(exp[exp["month"] != last_month]["supplier"].dropna())
    new_sups = last_sups - prev_sups
    if not new_sups:
        return []
    out = []
    for sup in list(new_sups)[:5]:
        sup_total = exp[exp["supplier"] == sup]["amount"].sum()
        out.append(_alert(
            "info", "supplier", f"ספק חדש: {sup}",
            f"ספק '{sup}' מופיע לראשונה בחודש {last_month} "
            f"עם סכום של ₪{sup_total:,.0f}. ודא שזו עסקה תקינה.",
            amount=float(sup_total), supplier=sup, month=last_month,
        ))
    return out


def _check_large_transactions(df: pd.DataFrame, threshold: float = 100000) -> list[dict]:
    """תנועות בסכום חריג ביחס למקובל בפרויקט."""
    if "source" not in df.columns:
        return []
    chash = df[df["source"] == "chashbashevet"]
    if chash.empty:
        return []
    exp = chash[chash["amount"] > threshold]
    if exp.empty:
        return []
    out = []
    for _, row in exp.nlargest(5, "amount").iterrows():
        sup = row.get("supplier", "")
        desc = row.get("description", "")
        out.append(_alert(
            "low", "expense", f"תנועה גדולה: ₪{row['amount']:,.0f}",
            f"ספק: {sup or 'לא זוהה'} — {desc or '-'}. "
            "ודא שהתנועה תקינה ולא נוצרה בטעות.",
            amount=float(row["amount"]), supplier=sup,
        ))
    return out


# ── Aggregator ─────────────────────────────────────────────

def collect_alerts(df: pd.DataFrame, project_id: str) -> list[dict]:
    """מחזיר רשימת התראות ממוינת לפי חומרה.

    Args:
        df: master.parquet (ייסונן לפרויקט בפנים).
        project_id: מזהה הפרויקט.

    Returns:
        רשימת dicts ממוינת לפי severity → high קודם.
    """
    if df.empty:
        return []
    project_df = df[df["project_id"] == project_id] \
        if "project_id" in df.columns else df
    if project_df.empty:
        return []

    alerts: list[dict] = []
    for check in (
        _check_project_in_loss,
        _check_months_without_income,
        _check_duplicate_invoices,
        _check_high_fuel_share,
        _check_tool_fuel_without_hours,
        _check_tool_hours_without_fuel,
        _check_new_suppliers,
        _check_large_transactions,
    ):
        try:
            if check is _check_project_in_loss:
                alerts.extend(check(df, project_id))
            else:
                alerts.extend(check(project_df))
        except Exception as e:
            logger.exception("Smart alert check %s failed: %s",
                              check.__name__, e)

    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 99))
    return alerts
