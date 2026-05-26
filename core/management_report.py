"""יצור דוח מנהלים לפרויקט — קובץ אקסל רב-גליונות.

הדוח מיועד לשליחה לבנק/מנהל/רואה חשבון, וכולל:
    - גיליון "סיכום": פרטי הפרויקט + KPIs ראשיים
    - גיליון "הכנסות": פירוט חשבוניות מכירה (927/951)
    - גיליון "הוצאות": הוצאות לפי קטגוריה
    - גיליון "ספקים": Top ספקים לפי סכום
    - גיליון "דלק": תדלוקים + מסקנת התאמה
    - גיליון "שעות עבודה": שעות לפי כלי
    - גיליון "חריגות": כל החריגות שזוהו
    - גיליון "פירוט תנועות": כל התנועות (אופציונלי - גדול)

כל הסכומים נכתבים כ-number עם פורמט #,##0 ב-Excel.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


def _meta_summary(project_meta: dict) -> pd.DataFrame:
    """גיליון "סיכום" — פרטי פרויקט + KPIs."""
    return pd.DataFrame([
        ("שם פרויקט", project_meta.get("project_name") or ""),
        ("מזהה", project_meta.get("project_id") or ""),
        ("לקוח", project_meta.get("client_name") or ""),
        ("אתר", project_meta.get("site_name") or ""),
        ("סטטוס", project_meta.get("status_he") or project_meta.get("status") or ""),
        ("תאריך התחלה", project_meta.get("start_date") or ""),
        ("תאריך סיום", project_meta.get("end_date") or ""),
        ("הערות", project_meta.get("notes") or ""),
        ("", ""),
        ("=== סיכום פיננסי ===", ""),
        ("הכנסות", project_meta.get("revenue", 0)),
        ("הוצאות", project_meta.get("expenses", 0)),
        ("רווח / הפסד", project_meta.get("profit", 0)),
        ("% רווחיות", project_meta.get("profit_pct", 0)),
        ("", ""),
        ("=== נפח פעילות ===", ""),
        ("תנועות", project_meta.get("num_transactions", 0)),
        ("ספקים", project_meta.get("num_suppliers", 0)),
        ("כלים", project_meta.get("num_tools", 0)),
        ("חריגות", project_meta.get("num_anomalies", 0)),
        ("חודשים בנתונים", ", ".join(project_meta.get("months", []) or [])),
        ("", ""),
        ("דוח הופק", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ], columns=["שדה", "ערך"])


def _income_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """הכנסות — שורות מחשבונות הכנסה אמיתיים בלבד."""
    from core.chashbashevet_loader import real_income_mask
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    inc = chash[real_income_mask(chash)] if not chash.empty else chash
    if inc.empty:
        return pd.DataFrame(columns=["תאריך", "חודש", "חשבון", "שם חשבון",
                                       "לקוח", "פרטים", "סכום (₪)"])
    out = inc.copy()
    out["amount_pos"] = out["amount"].abs()
    cols = [c for c in ["date", "month", "account_num", "account_name",
                          "supplier", "description", "amount_pos"]
            if c in out.columns]
    out = out[cols].sort_values("date" if "date" in cols else cols[0])
    out.columns = ["תאריך", "חודש", "חשבון", "שם חשבון", "לקוח",
                    "פרטים", "סכום (₪)"][:len(cols)]
    return out


def _expenses_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """הוצאות לפי קטגוריה."""
    from core.chashbashevet_loader import real_income_mask
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    if chash.empty:
        return pd.DataFrame(columns=["קטגוריה", "סה\"כ (₪)", "תנועות"])
    exp = chash[~real_income_mask(chash) & (chash.get("amount", 0) > 0)]
    if exp.empty:
        return pd.DataFrame(columns=["קטגוריה", "סה\"כ (₪)", "תנועות"])
    cat_col = "main_category" if "main_category" in exp.columns else "category"
    agg = exp.groupby(cat_col, dropna=False).agg(
        total=("amount", "sum"),
        count=("amount", "size"),
    ).reset_index().sort_values("total", ascending=False)
    agg.columns = ["קטגוריה", "סה\"כ (₪)", "תנועות"]
    return agg


def _suppliers_sheet(df: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """Top ספקים לפי סכום."""
    from core.chashbashevet_loader import real_income_mask
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    if chash.empty or "supplier" not in chash.columns:
        return pd.DataFrame(columns=["ספק", "סה\"כ (₪)", "חשבוניות", "חודשים פעילים"])
    exp = chash[~real_income_mask(chash) & (chash.get("amount", 0) > 0)]
    exp = exp[exp["supplier"].fillna("").astype(str).str.strip() != ""]
    if exp.empty:
        return pd.DataFrame(columns=["ספק", "סה\"כ (₪)", "חשבוניות", "חודשים פעילים"])
    agg = exp.groupby("supplier").agg(
        total=("amount", "sum"),
        count=("amount", "size"),
        months=("month", "nunique") if "month" in exp.columns else ("amount", "count"),
    ).reset_index().sort_values("total", ascending=False).head(top_n)
    agg.columns = ["ספק", "סה\"כ (₪)", "חשבוניות", "חודשים פעילים"]
    return agg


def _fuel_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """תדלוקים לפי כלי."""
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    if solar.empty:
        return pd.DataFrame(columns=["מס' רישוי", "שם כלי", "סה\"כ ליטרים",
                                        "תדלוקים"])
    cols = [c for c in ["license_num", "tool_name", "liters"] if c in solar.columns]
    if not cols:
        return pd.DataFrame(columns=["מס' רישוי", "שם כלי", "סה\"כ ליטרים",
                                        "תדלוקים"])
    agg = solar.groupby(["license_num", "tool_name"], dropna=False).agg(
        liters=("liters", "sum"),
        n=("liters", "size"),
    ).reset_index().sort_values("liters", ascending=False)
    agg.columns = ["מס' רישוי", "שם כלי", "סה\"כ ליטרים", "תדלוקים"]
    return agg


def _hours_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """שעות עבודה לפי כלי."""
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    if hours.empty or "work_hours" not in hours.columns:
        return pd.DataFrame(columns=["מס' רישוי", "שם כלי", "סה\"כ שעות",
                                        "ימי עבודה"])
    agg = hours.groupby(["license_num", "tool_name"], dropna=False).agg(
        h=("work_hours", "sum"),
        days=("date", "nunique") if "date" in hours.columns else ("work_hours", "count"),
    ).reset_index().sort_values("h", ascending=False)
    agg.columns = ["מס' רישוי", "שם כלי", "סה\"כ שעות", "ימי עבודה"]
    return agg


def _anomalies_sheet(project_id: str) -> pd.DataFrame:
    """חריגות במעקב."""
    try:
        from core import storage
        df = storage.list_quality_issues(project_id, status="all")
        if df.empty:
            return pd.DataFrame(columns=["תאריך", "סוג בדיקה", "ישות",
                                            "חומרה", "פרטים",
                                            "השפעה (₪)", "סטטוס"])
        SEV_HE = {"high": "גבוה", "medium": "בינוני", "low": "נמוך"}
        STATUS_HE = {"open": "פתוח", "resolved": "טופל", "dismissed": "נדחה"}
        out = pd.DataFrame({
            "תאריך": df.get("created_at", ""),
            "סוג בדיקה": df.get("check_type", ""),
            "ישות": df.get("entity", ""),
            "חומרה": df.get("severity", "").map(SEV_HE).fillna(df.get("severity", "")),
            "פרטים": df.get("details", ""),
            "השפעה (₪)": df.get("estimated_impact_nis", 0),
            "סטטוס": df.get("status", "").map(STATUS_HE).fillna(df.get("status", "")),
        })
        return out
    except Exception as e:
        logger.exception("Failed to load anomalies: %s", e)
        return pd.DataFrame()


def _full_transactions_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """כל התנועות בעברית."""
    if df.empty:
        return df
    cols = [c for c in ["date", "month", "account_num", "account_name",
                          "supplier", "description", "amount", "source"]
            if c in df.columns]
    out = df[cols].copy()
    heb = {"date": "תאריך", "month": "חודש", "account_num": "חשבון",
           "account_name": "שם חשבון", "supplier": "ספק",
           "description": "פרטים", "amount": "סכום (₪)", "source": "מקור"}
    out.columns = [heb.get(c, c) for c in cols]
    # תרגום source לעברית
    src_he = {"chashbashevet": "כרטיס הנהלה", "solar": "תדלוקים",
              "hours": "שעות עבודה", "manual": "ידני",
              "balance": "מאזן בוחן"}
    if "מקור" in out.columns:
        out["מקור"] = out["מקור"].map(src_he).fillna(out["מקור"])
    return out


# ── Excel writer with money formatting ──────────────────────

def _apply_number_formats(writer, sheet_name: str, df: pd.DataFrame) -> None:
    """מחיל פורמט #,##0 על עמודות סכומים ב-Excel."""
    try:
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        money_fmt = workbook.add_format({"num_format": "#,##0"}) \
            if hasattr(workbook, "add_format") else None
        if money_fmt is None:
            return
        money_keywords = ("סכום", "סה\"כ", "₪", "השפעה", "ליטרים", "שעות")
        for col_idx, col_name in enumerate(df.columns):
            if any(k in str(col_name) for k in money_keywords):
                # +1 כי הכותרת בשורה 0; openpyxl/xlsxwriter סופרים מ-0
                worksheet.set_column(col_idx, col_idx, 16, money_fmt)
            else:
                worksheet.set_column(col_idx, col_idx, 18)
    except Exception as e:
        logger.warning("Could not apply number format to %s: %s", sheet_name, e)


def export_management_report(project_id: str, df_master: pd.DataFrame,
                                include_transactions: bool = False) -> bytes:
    """מחזיר קובץ Excel (bytes) של דוח המנהלים לפרויקט.

    Args:
        project_id: מזהה הפרויקט.
        df_master: ה-master.parquet (יסונן ל-project_id בפנים).
        include_transactions: אם True — מוסיף גיליון עם כל התנועות (גדול).

    Returns:
        bytes של קובץ xlsx.
    """
    from core.project_aggregator import project_summary
    from core.project_store import get_project_by_id, STATUS_HE

    df = df_master[df_master["project_id"] == project_id] \
        if not df_master.empty and "project_id" in df_master.columns \
        else df_master

    # פרטי הפרויקט מהרגיסטרי + summary
    proj = get_project_by_id(project_id) or {"project_id": project_id}
    summary = project_summary(df_master, project_id)
    proj_full = {**proj, **summary}
    proj_full["status_he"] = STATUS_HE.get(proj.get("status", ""), proj.get("status", ""))

    buf = io.BytesIO()
    # נסיון להשתמש ב-xlsxwriter עם פורמטים; ליפול ל-openpyxl אם אין.
    try:
        engine = "xlsxwriter"
        import xlsxwriter  # noqa: F401
    except ImportError:
        engine = "openpyxl"

    with pd.ExcelWriter(buf, engine=engine) as writer:
        # 1) סיכום
        meta_df = _meta_summary(proj_full)
        meta_df.to_excel(writer, sheet_name="סיכום", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "סיכום", meta_df)

        # 2) הכנסות
        inc = _income_sheet(df)
        inc.to_excel(writer, sheet_name="הכנסות", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "הכנסות", inc)

        # 3) הוצאות לפי קטגוריה
        exp = _expenses_by_category(df)
        exp.to_excel(writer, sheet_name="הוצאות", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "הוצאות", exp)

        # 4) ספקים
        sup = _suppliers_sheet(df)
        sup.to_excel(writer, sheet_name="ספקים", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "ספקים", sup)

        # 5) דלק
        fuel = _fuel_sheet(df)
        fuel.to_excel(writer, sheet_name="דלק", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "דלק", fuel)

        # 6) שעות עבודה
        hrs = _hours_sheet(df)
        hrs.to_excel(writer, sheet_name="שעות עבודה", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "שעות עבודה", hrs)

        # 7) חריגות
        anom = _anomalies_sheet(project_id)
        anom.to_excel(writer, sheet_name="חריגות", index=False)
        if engine == "xlsxwriter":
            _apply_number_formats(writer, "חריגות", anom)

        # 8) פירוט תנועות (אופציונלי)
        if include_transactions:
            full = _full_transactions_sheet(df)
            if not full.empty:
                full.to_excel(writer, sheet_name="פירוט תנועות", index=False)
                if engine == "xlsxwriter":
                    _apply_number_formats(writer, "פירוט תנועות", full)

    buf.seek(0)
    return buf.getvalue()
