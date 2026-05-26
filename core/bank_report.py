"""דוח פרויקט לבנק — קובץ Excel מפורט המתאים לשליחה לבנק.

ההבדל מ-management_report:
- כולל פרטי חברה
- מבנה תזרים חודשי מפורט יותר
- מסקנה ניהולית מפורטת בטקסט חופשי
- חתימת חברה

מבנה הגיליונות:
    1. כריכה  — לוגו / כותרת / פרטי החברה והפרויקט
    2. סיכום  — KPIs פיננסיים
    3. תזרים  — חודש אחר חודש (הכנסות, הוצאות, רווח)
    4. הוצאות — שבירה לפי קטגוריה
    5. הכנסות — פירוט מקורות
    6. ציוד   — פרטי כלים
    7. מסקנה  — טקסט ניהולי

מטבע: ש"ח. כל הסכומים #,##0.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


COMPANY_NAME = 'מ. אילון אביב נכסים בע"מ'


def _cover_sheet(project_meta: dict) -> pd.DataFrame:
    return pd.DataFrame([
        ("דוח פרויקט לבנק", ""),
        ("", ""),
        ("פרטי חברה", ""),
        ("שם חברה", COMPANY_NAME),
        ("", ""),
        ("פרטי פרויקט", ""),
        ("שם פרויקט", project_meta.get("project_name") or ""),
        ("מזהה", project_meta.get("project_id") or ""),
        ("לקוח", project_meta.get("client_name") or ""),
        ("אתר", project_meta.get("site_name") or ""),
        ("תאריך התחלה", project_meta.get("start_date") or ""),
        ("תאריך סיום צפוי", project_meta.get("end_date") or ""),
        ("סטטוס", project_meta.get("status_he") or ""),
        ("", ""),
        ("תאריך הפקת הדוח", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ], columns=["סעיף", "ערך"])


def _financial_summary(summary: dict) -> pd.DataFrame:
    return pd.DataFrame([
        ("סה\"כ הכנסות", summary.get("revenue", 0)),
        ("סה\"כ הוצאות", summary.get("expenses", 0)),
        ("רווח / הפסד", summary.get("profit", 0)),
        ("% רווחיות", summary.get("profit_pct", 0)),
        ("", ""),
        ("מספר תנועות", summary.get("num_transactions", 0)),
        ("מספר ספקים", summary.get("num_suppliers", 0)),
        ("מספר כלים", summary.get("num_tools", 0)),
        ("חודשים פעילים", len(summary.get("months", []) or [])),
    ], columns=["סעיף", "ערך"])


def _monthly_cashflow(df: pd.DataFrame) -> pd.DataFrame:
    """תזרים חודשי: הכנסות, הוצאות, רווח, יתרה מצטברת."""
    from core.chashbashevet_loader import real_income_mask
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    if chash.empty or "month" not in chash.columns:
        return pd.DataFrame(columns=["חודש", "הכנסות", "הוצאות",
                                        "רווח / הפסד", "יתרה מצטברת"])
    income_mask = real_income_mask(chash)
    expense_mask = ~income_mask & (chash["amount"] > 0)

    rows = []
    cumulative = 0
    for month, grp in chash.groupby("month"):
        inc = float(-grp[income_mask.loc[grp.index]]["amount"].sum()) \
            if income_mask.loc[grp.index].any() else 0
        exp = float(grp[expense_mask.loc[grp.index]]["amount"].sum()) \
            if expense_mask.loc[grp.index].any() else 0
        profit = inc - exp
        cumulative += profit
        rows.append({"חודש": month, "הכנסות": round(inc, 0),
                       "הוצאות": round(exp, 0),
                       "רווח / הפסד": round(profit, 0),
                       "יתרה מצטברת": round(cumulative, 0)})

    def _sort_key(s):
        try:
            return pd.to_datetime(s["חודש"], format="%m-%Y")
        except Exception:
            return pd.Timestamp.min

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out["_k"] = df_out.apply(_sort_key, axis=1)
        df_out = df_out.sort_values("_k").drop(columns=["_k"]).reset_index(drop=True)
    return df_out


def _expenses_by_category(df: pd.DataFrame) -> pd.DataFrame:
    from core.management_report import _expenses_by_category as inner
    return inner(df)


def _income_sources(df: pd.DataFrame) -> pd.DataFrame:
    from core.chashbashevet_loader import real_income_mask
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    if chash.empty:
        return pd.DataFrame(columns=["חשבון הכנסה", "סה\"כ (₪)", "תנועות"])
    inc = chash[real_income_mask(chash)]
    if inc.empty:
        return pd.DataFrame(columns=["חשבון הכנסה", "סה\"כ (₪)", "תנועות"])
    agg = inc.groupby("account_name", dropna=False).agg(
        total=("amount", lambda s: float(-s.sum())),
        count=("amount", "size"),
    ).reset_index().sort_values("total", ascending=False)
    agg.columns = ["חשבון הכנסה", "סה\"כ (₪)", "תנועות"]
    return agg


def _equipment_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """כלים פעילים בפרויקט."""
    from pipeline import _load_tools_registry
    tools_reg = _load_tools_registry()
    if "source" in df.columns:
        solar = df[df["source"] == "solar"]
        hours = df[df["source"] == "hours"]
    else:
        solar, hours = df.iloc[0:0], df.iloc[0:0]

    by_license: dict = {}
    for _, r in solar.iterrows() if not solar.empty else []:
        lic = r.get("license_num")
        if pd.isna(lic):
            continue
        lic = int(lic)
        by_license.setdefault(lic, {"tool_name": r.get("tool_name", ""),
                                       "liters": 0, "hours": 0})
        by_license[lic]["liters"] += float(r.get("liters", 0) or 0)
    for _, r in hours.iterrows() if not hours.empty else []:
        lic = r.get("license_num")
        if pd.isna(lic):
            continue
        lic = int(lic)
        by_license.setdefault(lic, {"tool_name": r.get("tool_name", ""),
                                       "liters": 0, "hours": 0})
        by_license[lic]["hours"] += float(r.get("work_hours", 0) or 0)

    if not by_license:
        return pd.DataFrame(columns=["מס' רישוי", "שם כלי", "ליטרים",
                                        "שעות עבודה", "ל'/ש'"])

    rows = []
    for lic, data in by_license.items():
        lph = round(data["liters"] / data["hours"], 2) if data["hours"] > 0 else 0
        rows.append({"מס' רישוי": lic, "שם כלי": data["tool_name"],
                       "ליטרים": round(data["liters"], 0),
                       "שעות עבודה": round(data["hours"], 1),
                       "ל'/ש'": lph})
    return pd.DataFrame(rows).sort_values("ליטרים", ascending=False)


def _management_conclusion(summary: dict) -> pd.DataFrame:
    """מסקנה ניהולית בטקסט חופשי."""
    revenue = summary.get("revenue", 0)
    expenses = summary.get("expenses", 0)
    profit = summary.get("profit", 0)
    pct = summary.get("profit_pct", 0)
    n_months = len(summary.get("months", []) or [])
    if revenue == 0:
        verdict = ("⚠️ הפרויקט בהפסד מלא — אין הכנסות, רק הוצאות. "
                   "מומלץ לבדוק אם הפרויקט בשלב התחלתי או שיש בעיה ברישום ההכנסות.")
    elif profit > 0:
        verdict = (f"✅ הפרויקט רווחי. רווח של ₪{profit:,.0f} ({pct:.1f}%) "
                   f"לאורך {n_months} חודשי פעילות.")
    elif profit > -revenue * 0.05:
        verdict = (f"⚠️ הפרויקט קרוב לאיזון. הפסד של ₪{abs(profit):,.0f} "
                   "אבל בטווח הקבילות. מומלץ למקד הוצאות.")
    else:
        verdict = (f"🚨 הפרויקט בהפסד משמעותי של ₪{abs(profit):,.0f} "
                   f"({pct:.1f}%). דורש בדיקה דחופה.")

    return pd.DataFrame([
        ("מסקנה ניהולית", verdict),
        ("", ""),
        ("פרטים נוספים", ""),
        ("סה\"כ תנועות בפרויקט", summary.get("num_transactions", 0)),
        ("מספר ספקים פעילים", summary.get("num_suppliers", 0)),
        ("מספר כלים בפרויקט", summary.get("num_tools", 0)),
        ("מספר חריגות במעקב", summary.get("num_anomalies", 0)),
    ], columns=["סעיף", "ערך"])


def export_bank_report(project_id: str, df_master: pd.DataFrame) -> bytes:
    """מחזיר bytes של דוח לבנק (xlsx רב-גליונות)."""
    from core.project_aggregator import project_summary
    from core.project_store import get_project_by_id, STATUS_HE

    df = df_master[df_master["project_id"] == project_id] \
        if not df_master.empty and "project_id" in df_master.columns \
        else df_master

    proj = get_project_by_id(project_id) or {"project_id": project_id}
    summary = project_summary(df_master, project_id)
    proj_full = {**proj, **summary}
    proj_full["status_he"] = STATUS_HE.get(proj.get("status", ""),
                                              proj.get("status", ""))

    buf = io.BytesIO()
    try:
        engine = "xlsxwriter"
        import xlsxwriter  # noqa: F401
    except ImportError:
        engine = "openpyxl"

    sheets: list[tuple[str, pd.DataFrame]] = [
        ("כריכה", _cover_sheet(proj_full)),
        ("סיכום", _financial_summary(summary)),
        ("תזרים חודשי", _monthly_cashflow(df)),
        ("הוצאות", _expenses_by_category(df)),
        ("הכנסות", _income_sources(df)),
        ("ציוד וכלים", _equipment_sheet(df)),
        ("מסקנה", _management_conclusion(summary)),
    ]

    with pd.ExcelWriter(buf, engine=engine) as writer:
        for sheet_name, df_sheet in sheets:
            df_sheet.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            if engine == "xlsxwriter":
                _apply_formats(writer, sheet_name[:31], df_sheet)
    buf.seek(0)
    return buf.getvalue()


def _apply_formats(writer, sheet_name: str, df: pd.DataFrame) -> None:
    """פורמט #,##0 על עמודות סכומים."""
    try:
        wb = writer.book
        ws = writer.sheets[sheet_name]
        money_fmt = wb.add_format({"num_format": "#,##0"})
        money_keywords = ("סכום", "סה\"כ", "₪", "הכנסות", "הוצאות",
                           "רווח", "הפסד", "יתרה", "מצטברת", "ליטרים", "שעות")
        for col_idx, col_name in enumerate(df.columns):
            if any(k in str(col_name) for k in money_keywords):
                ws.set_column(col_idx, col_idx, 18, money_fmt)
            else:
                ws.set_column(col_idx, col_idx, 20)
    except Exception as e:
        logger.warning("apply_formats %s: %s", sheet_name, e)
