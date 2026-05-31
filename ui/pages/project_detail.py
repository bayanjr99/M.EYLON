"""דף ייעודי לפרויקט בודד - 9 טאבים, כל הנתונים מסוננים לפי project_id."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core import anomaly_detector, project_aggregator
from ui.components import (
    breadcrumb, empty_state, ins, kpi_block, render_kpi_group, sec,
    exec_summary, blk,
)
from ui.formatters import (
    format_currency, format_number, format_decimal, format_percent,
    build_column_config, display_dataframe,
)


# ── קטגוריזציה לפי מילות מפתח (על account_name או description) ──────
# כל מפתח = קטגוריה; הערך = רשימת מילות מפתח לחיפוש case-insensitive.
KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "income": ["הכנסות", "חיוב ספק", "מכירות"],
    "salary": ["שכר עבודה", "עובדים זרים", "ביטוח לאומי", "גמל",
               "פיצויים", "קרן השתלמות", "שכר", "עובד"],
    "fuel": ["סולר", "בנזין", "דלק", "חשמל רכבים", "תדלוק"],
    "maintenance": ["אחזקת כלי", "אחזקת רכב", "אחזקה", "מוסך",
                    "תיקונים", "תיקון", "חלפים"],
    "subcontractors": ["קבלני משנה", "קבלן משנה", "קבלן"],
    "materials": ["חומרים", "ספקי חומרים", "חצץ", "בטון"],
    "rentals": ["שכירות ציוד", "שכר ציוד", "השכרה"],
    "insurance": ["ביטוח", "ביטוחים"],
}


def _has_keyword(text: str, keywords: list[str]) -> bool:
    """True אם אחת ממילות המפתח מופיעה בטקסט (case-insensitive)."""
    if not isinstance(text, str):
        return False
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


def _filter_by_keywords(df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    """מסנן שורות שבהן account_name או description מכיל מילת מפתח."""
    if df.empty:
        return df
    name_col = df["account_name"].fillna("") if "account_name" in df.columns else pd.Series([""] * len(df))
    desc_col = df["description"].fillna("") if "description" in df.columns else pd.Series([""] * len(df))
    mask = name_col.apply(lambda s: _has_keyword(s, keywords)) | \
           desc_col.apply(lambda s: _has_keyword(s, keywords))
    return df[mask]


def _fmt_money(v: float) -> str:
    """Backward-compat alias to format_currency (full ₪1,250,000 format)."""
    return format_currency(v, blank="₪0")


def _clean(v) -> str:
    """NaN/None/ריק → ''."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def render_project_detail(df_master: pd.DataFrame, project_meta: dict) -> None:
    """מסך פרויקט: header + 9 טאבים. כל הטאבים מסוננים ל-project_id."""
    from core.project_store import validate_project_status, STATUS_HE
    project_id = project_meta["project_id"]
    project_name = _clean(project_meta.get("project_name")) or project_id
    client = _clean(project_meta.get("client_name")) or _clean(project_meta.get("notes")) or "—"
    status_code = validate_project_status(project_meta.get("status", "active"))
    status = STATUS_HE.get(status_code, status_code)

    # ── אם נלחץ "ערוך פרויקט" - מציגים טופס במקום הדף ──
    if st.session_state.get("edit_project_id") == project_id:
        from ui.pages.projects_list import _render_edit_project_form
        if st.button("← חזרה לפרויקט", key="back_from_edit",
                       use_container_width=False):
            st.session_state.pop("edit_project_id", None)
            st.rerun()
        _render_edit_project_form(project_id)
        return

    # ── Drill-Down: אם נבחר ספק/לקוח/כלי/חודש → מציגים מסך פירוט ──
    from ui.pages.detail_view import render_detail_view
    if render_detail_view(df_master, project_meta):
        return

    # ── Back / Edit (שורה אחת מעל הכותרת) ──
    back_col, edit_col, _spacer = st.columns([1, 2, 5])
    with back_col:
        if st.button("← חזרה לרשימה", key="back_to_list", use_container_width=True):
            st.session_state.pop("selected_project_id", None)
            st.rerun()
    with edit_col:
        if st.button("✏️ ערוך פרויקט", key="edit_project_btn",
                       use_container_width=True, type="primary"):
            st.session_state["edit_project_id"] = project_id
            st.rerun()

    # ── Header card ─────────────────────────────────────────
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:12px;
        padding:8px 16px;background:linear-gradient(135deg,#F0FDF4,#FFFFFF);
        border-radius:10px;border:1px solid var(--brand-primary-mid);margin-top:6px">
          <i class="ti ti-buildings" style="font-size:22px;color:var(--brand-primary)"></i>
          <div style="flex:1;min-width:0">
            <div style="font-size:15px;font-weight:800;color:var(--ink-strong);
              line-height:1.2">{project_name}</div>
            <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">
              לקוח: <b>{client}</b> · סטטוס: <b>{status}</b> · מזהה: <code>{project_id}</code>
            </div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── סינון ל-project_id בלבד ──────────────────────────────
    df = df_master[df_master["project_id"] == project_id] if not df_master.empty else df_master

    if df.empty:
        # אבחון - להראות בדיוק למה אין דאטה
        import os
        from pipeline import MASTER_PARQUET
        master_exists = MASTER_PARQUET.exists()
        master_size = MASTER_PARQUET.stat().st_size if master_exists else 0
        all_ids = sorted(df_master["project_id"].dropna().unique()) if not df_master.empty else []
        diag = (
            f"<div style='background:#FEF2F2;border:1px solid #FECACA;"
            f"border-radius:8px;padding:10px 14px;margin:10px 0;font-size:11px;"
            f"font-family:monospace;color:#7F1D1D;direction:rtl;text-align:right'>"
            f"<b>אבחון:</b><br>"
            f"תיקיית עבודה: {os.getcwd()}<br>"
            f"נתיב מאסטר: {MASTER_PARQUET}<br>"
            f"קיים: {'כן' if master_exists else 'לא'}, גודל: {master_size:,} בייטים<br>"
            f"סה\"כ שורות במאסטר: {len(df_master):,}<br>"
            f"מזהי פרויקטים במאסטר: {all_ids}<br>"
            f"מחפש מזהה פרויקט: <b>{project_id!r}</b><br>"
            f"</div>"
        )
        empty_state(
            icon="ti-database-off",
            title=f"אין עדיין נתונים לפרויקט {project_name}",
            body_html=(
                diag +
                "כדי לטעון נתונים:"
                "<ul>"
                "<li>שים קבצי חודש בתיקיית הפרויקט</li>"
                "<li>הקבצים: מאזן, כרטיס הנהלה, "
                "דוח תדלוקים, דוח שעות עבודה</li>"
                "<li>בנה מחדש את מאסטר הנתונים</li>"
                "<li>חזור לרשימה ופתח שוב את הפרויקט</li>"
                "</ul>"
            ),
        )
        return

    # ── פילטר חודש אחיד לכל המסכים ──
    # מקור אמת יחיד לתקופה — כל ה-KPI, גרפים, טבלאות וטאבים
    # מחושבים מאותו filtered_df.
    available_months = sorted(df["month"].dropna().unique()) \
        if "month" in df.columns else []
    if available_months:
        from ui.formatters import format_number
        mc1, _ = st.columns([2, 5])
        with mc1:
            month_options = ["כל החודשים"] + list(available_months)
            month_choice = st.selectbox(
                f"📅 פילטר חודש ({format_number(len(available_months))} חודשים זמינים)",
                month_options,
                key=f"month_filter_{project_id}",
                help="הבחירה משפיעה על כל הטאבים, ה-KPIs, ההתראות והדוחות "
                     "בדף הפרויקט.",
            )
        if month_choice != "כל החודשים":
            df = df[df["month"] == month_choice]
            # df_master_scoped משמש ל-project_summary ולקריאות שמשתמשות
            # עדיין ב-df_master השלם פנימית
            df_master_scoped = df_master[
                (df_master["project_id"] == project_id) &
                (df_master["month"] == month_choice)
            ] if not df_master.empty else df_master
        else:
            df_master_scoped = df_master
    else:
        month_choice = "כל החודשים"
        df_master_scoped = df_master

    summary = project_aggregator.project_summary(df_master_scoped, project_id)

    # ── Period header: scope + months + tx count + מקורות נתונים ──
    months_str = ", ".join(summary["months"]) if summary["months"] else "—"
    scope_text = (f"📅 <b>חודש {month_choice}</b>"
                  if month_choice != "כל החודשים"
                  else f'📅 <b>{len(summary["months"])} חודשים</b>: {months_str}')
    # אינדיקטור מקורות נתונים שנטענו ל-scope הנוכחי (פריט מצב נתונים)
    sources_present = ""
    if "source" in df.columns and not df.empty:
        labels = [_SOURCE_HE.get(s, s) for s in df["source"].dropna().unique()]
        if labels:
            sources_present = (f'<span class="sep">·</span> מקורות: '
                               f'{" · ".join(sorted(set(labels)))}')
    period_html = (
        f'<div class="period-header">'
        f'<span>{scope_text}'
        f'<span class="sep">·</span> {summary["num_transactions"]:,} תנועות'
        f'<span class="sep">·</span> {summary["num_suppliers"]} ספקים'
        f'{sources_present}</span>'
        f'<span class="tag">תמונת פרויקט</span>'
        f'</div>'
    )
    st.markdown(period_html, unsafe_allow_html=True)

    # ── 6 טאבים ראשיים ──
    tabs = st.tabs([
        "📊 סקירה כללית",
        "💰 כספים",
        "⛽ סולר",
        "🕒 שעות עבודה",
        "🚜 כלים",
        "🚨 חריגים ובדיקות",
    ])

    with tabs[0]:
        breadcrumb("פרויקט", project_name, "סקירה כללית")
        _tab_overview(df, summary)

    with tabs[1]:
        # כספים: 4 sub-tabs
        sub = st.tabs(["הכנסות", "הוצאות", "ספקים", "פירוט תנועות"])
        with sub[0]:
            breadcrumb("כספים", "הכנסות")
            _tab_income(df)
        with sub[1]:
            breadcrumb("כספים", "הוצאות")
            _tab_expenses(df)
        with sub[2]:
            breadcrumb("כספים", "ספקים")
            _subtab_suppliers_finance(df, project_meta)
        with sub[3]:
            breadcrumb("כספים", "פירוט תנועות")
            _tab_transactions(df)

    with tabs[2]:
        # סולר: 3 sub-tabs
        sub = st.tabs(["קניות סולר", "שימוש בסולר", "סיכום מלאי"])
        with sub[0]:
            breadcrumb("סולר", "קניות סולר")
            _subtab_fuel_purchases(df, project_meta)
            with st.expander("➕ הזנה ידנית של קניות סולר"):
                from ui.pages.field_data_entry import (
                    _render_fuel_quick_form, _render_sub_tab,
                )
                _render_fuel_quick_form(project_id)
                _render_sub_tab("fuel_logs", project_id, None, None)
        with sub[1]:
            breadcrumb("סולר", "שימוש בסולר")
            _subtab_fuel_usage(df, project_meta)
        with sub[2]:
            breadcrumb("סולר", "סיכום מלאי")
            _subtab_fuel_inventory(df, project_meta)

    with tabs[3]:
        # שעות עבודה: 3 sub-tabs (עם הזנה ידנית בכל אחד)
        sub = st.tabs(["שעות עבודה כלים", "שעות עובדים", "שעות קבלני משנה"])
        with sub[0]:
            breadcrumb("שעות עבודה", "כלים")
            _subtab_equipment_hours(df, project_meta)
            with st.expander("➕ הזנה ידנית של שעות עבודה כלים"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("equipment_work_logs", project_id, None, None)
        with sub[1]:
            breadcrumb("שעות עבודה", "עובדים")
            _tab_employees(df, project_meta)
            with st.expander("➕ הזנה ידנית של שעות עובדים"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("employee_work_logs", project_id, None, None)
        with sub[2]:
            breadcrumb("שעות עבודה", "קבלני משנה")
            _subtab_contractors_field(df, project_meta)
            with st.expander("➕ הזנה ידנית של שעות קבלני משנה"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("contractor_work_logs", project_id, None, None)

    with tabs[4]:
        # כלים: 4 sub-tabs
        sub = st.tabs(["רשימת כלים", "פעילות כלים", "עלויות כלי",
                        "ניתוח כלי"])
        with sub[0]:
            breadcrumb("כלים", "רשימת כלים")
            from ui.pages.field_data_entry import _render_tools_management
            _render_tools_management()
        with sub[1]:
            breadcrumb("כלים", "פעילות כלים")
            _tab_vehicles_tools(df, project_meta)
        with sub[2]:
            breadcrumb("כלים", "עלויות כלי")
            _subtab_maintenance(df, project_meta)
            with st.expander("➕ הזנה ידנית של טיפולים ואחזקה"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("maintenance_logs", project_id, None, None)
        with sub[3]:
            breadcrumb("כלים", "ניתוח כלי")
            _subtab_cost_per_hour(df, project_meta)

    with tabs[5]:
        # חריגים ובדיקות: מרכז את כל ההתראות והבדיקות במקום אחד
        breadcrumb("פרויקט", project_name, "חריגים ובדיקות")
        _render_smart_alerts(df, project_id)
        st.markdown("---")
        _tab_qa(df, project_meta)


# ─── Tab 1: סקירה כללית ─────────────────────────────────────
def _render_smart_alerts(df: pd.DataFrame, project_id: str) -> None:
    """מציג התראות חכמות בראש מסך הסקירה.

    מתקפל בתוך expander אם יש מעל 3 התראות, אחרת מציג ישירות.
    """
    from core.smart_alerts import collect_alerts, SEVERITY_COLOR
    alerts = collect_alerts(df, project_id)
    if not alerts:
        ins("green", "✓", "אין התראות פתוחות",
            "המערכת לא זיהתה בעיות אוטומטיות בנתוני הפרויקט.")
        return

    high = [a for a in alerts if a["severity"] == "high"]
    medium = [a for a in alerts if a["severity"] == "medium"]
    low_info = [a for a in alerts if a["severity"] in ("low", "info")]

    sec("🚨 התראות חכמות",
        meta=f"{len(high)} גבוהות · {len(medium)} בינוניות · "
             f"{len(low_info)} נמוכות/מידע")

    # התראות גבוהות תמיד מוצגות
    for a in high:
        ins(SEVERITY_COLOR[a["severity"]], "🚨", a["title"], a["body"])

    # בינוניות בקיפול
    if medium:
        with st.expander(f"⚠️ {len(medium)} התראות בינוניות", expanded=not high):
            for a in medium:
                ins(SEVERITY_COLOR[a["severity"]], "⚠️", a["title"], a["body"])

    # נמוכות/מידע בקיפול נפרד
    if low_info:
        with st.expander(f"ℹ️ {len(low_info)} התראות נמוכות / מידע",
                           expanded=False):
            for a in low_info:
                ins(SEVERITY_COLOR[a["severity"]], "ℹ️", a["title"], a["body"])


def _overview_top_drivers(df: pd.DataFrame) -> dict:
    """מחזיר את מניעי ההוצאה המרכזיים: קטגוריה/ספק/חודש יקרים ביותר.

    מבוסס על שורות חשבשבת שאינן הכנסה (נטו חובה−זכות), כדי להתאים
    ללוגיקת ההוצאות בכל המערכת.
    """
    out = {"top_category": None, "top_category_amount": 0.0,
           "top_supplier": None, "top_supplier_amount": 0.0,
           "worst_month": None, "worst_month_amount": 0.0}
    if df.empty or "source" not in df.columns:
        return out
    from core.chashbashevet_loader import real_income_mask
    chash = df[df["source"] == "chashbashevet"]
    if chash.empty:
        return out
    exp = chash[~real_income_mask(chash)]
    if exp.empty:
        return out
    cat_col = "main_category" if "main_category" in exp.columns else "category"
    if cat_col in exp.columns:
        by_cat = exp.groupby(cat_col)["amount"].sum().sort_values(ascending=False)
        if not by_cat.empty and by_cat.iloc[0] > 0:
            out["top_category"] = str(by_cat.index[0])
            out["top_category_amount"] = float(by_cat.iloc[0])
    if "supplier" in exp.columns:
        sup = exp[exp["supplier"].fillna("").astype(str).str.strip() != ""]
        if not sup.empty:
            by_sup = sup.groupby("supplier")["amount"].sum().sort_values(ascending=False)
            if not by_sup.empty and by_sup.iloc[0] > 0:
                out["top_supplier"] = str(by_sup.index[0])
                out["top_supplier_amount"] = float(by_sup.iloc[0])
    if "month" in exp.columns:
        by_month = exp.groupby("month")["amount"].sum().sort_values(ascending=False)
        if not by_month.empty and by_month.iloc[0] > 0:
            out["worst_month"] = str(by_month.index[0])
            out["worst_month_amount"] = float(by_month.iloc[0])
    return out


def _render_overview_executive(df: pd.DataFrame, summary: dict) -> None:
    """סיכום מנהלים קצר בראש הסקירה: סטטוס, מניעים מרכזיים וטקסט תובנות.

    ההתראות המלאות עברו לטאב '🚨 חריגים ובדיקות' כדי למנוע כפילות;
    כאן מוצג רק תקציר ניהולי + הפניה.
    """
    from ui.formatters import format_currency
    profit = summary.get("profit", 0.0)
    in_loss = profit < 0
    status = "bad" if in_loss else "good"
    status_text = "הפרויקט בהפסד" if in_loss else "הפרויקט ברווח"

    drivers = _overview_top_drivers(df)
    cat_txt = drivers["top_category"] or "—"
    cat_sub = format_currency(drivers["top_category_amount"]) if drivers["top_category"] else "אין נתונים"
    sup_txt = drivers["top_supplier"] or "—"
    sup_sub = format_currency(drivers["top_supplier_amount"]) if drivers["top_supplier"] else "אין נתונים"

    exec_summary(
        title="סיכום מנהלים",
        status=status,
        status_text=f"{status_text} · {format_currency(abs(profit))}",
        questions=[
            ("רווח / הפסד", format_currency(profit),
             f"הכנסות {format_currency(summary.get('revenue', 0))} · "
             f"הוצאות {format_currency(summary.get('expenses', 0))}"),
            ("הקטגוריה היקרה ביותר", cat_txt, cat_sub),
            ("הספק המרכזי", sup_txt, sup_sub),
        ],
    )

    # ── תובנות עיקריות (טקסט אוטומטי) ──
    verb = "בהפסד" if in_loss else "ברווח"
    parts = [f"הפרויקט נמצא <b>{verb}</b> של {format_currency(abs(profit))}"]
    if drivers["top_category"]:
        parts.append(f"ההוצאה הגדולה ביותר היא בקטגוריית <b>{cat_txt}</b> "
                     f"({format_currency(drivers['top_category_amount'])})")
    if drivers["top_supplier"]:
        parts.append(f"הספק המרכזי הוא <b>{sup_txt}</b> "
                     f"({format_currency(drivers['top_supplier_amount'])})")
    if drivers["worst_month"]:
        parts.append(f"החודש הבעייתי ביותר הוא <b>{drivers['worst_month']}</b> "
                     f"({format_currency(drivers['worst_month_amount'])} הוצאות)")
    blk("תובנות עיקריות", ". ".join(parts) + ".", cls="warm")

    # ── הפניה לטאב חריגים אם יש התראות חמורות ──
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None
    if project_id:
        try:
            from core.smart_alerts import collect_alerts
            alerts = collect_alerts(df, project_id)
            high = sum(1 for a in alerts if a["severity"] == "high")
            if alerts:
                msg = (f"זוהו <b>{len(alerts)}</b> התראות"
                       + (f" ({high} בחומרה גבוהה)" if high else "")
                       + ". הפירוט המלא בטאב <b>🚨 חריגים ובדיקות</b>.")
                st.markdown(
                    f'<div class="focus {"red" if high else "amber"}">{msg}</div>',
                    unsafe_allow_html=True,
                )
        except Exception:
            pass


def _tab_overview(df: pd.DataFrame, summary: dict) -> None:
    # ── סיכום מנהלים בראש המסך (ההתראות המלאות בטאב חריגים) ──
    _render_overview_executive(df, summary)

    kpis_fin = [
        kpi_block("הכנסות", _fmt_money(summary["revenue"]),
                  accent="green", icon="ti-cash-banknote"),
        kpi_block("הוצאות", _fmt_money(summary["expenses"]),
                  accent="red", icon="ti-coin"),
        kpi_block("רווח / הפסד", _fmt_money(summary["profit"]),
                  accent="green" if summary["profit"] >= 0 else "red",
                  icon="ti-wallet"),
        kpi_block("% רווחיות", f"{summary['profit_pct']:.1f}%",
                  accent="green" if summary["profit_pct"] >= 0 else "red",
                  icon="ti-percentage"),
    ]
    kpis_ops = [
        kpi_block("יתרת לקוחות", _fmt_money(summary["revenue"] - summary["expenses"]),
                  accent="slate", icon="ti-users",
                  chips="הכנסות פחות הוצאות"),
        kpi_block("חריגות", str(summary["num_anomalies"]),
                  accent="red" if summary["num_anomalies"] else "green",
                  icon="ti-alert-triangle"),
        kpi_block("ספקים", str(summary["num_suppliers"]),
                  accent="blue", icon="ti-truck"),
        kpi_block("כלים בשטח", str(summary["num_tools"]),
                  accent="amber", icon="ti-bulldozer"),
    ]
    render_kpi_group(kpis_fin, "פיננסי", "ti-cash-banknote")
    render_kpi_group(kpis_ops, "תפעולי", "ti-activity")

    # ── Top 10 הוצאות + Top 10 ספקים ──
    chash_exp = df[(df["source"] == "chashbashevet") & (df["amount"] > 0)] \
        if "source" in df.columns else df.iloc[0:0]
    if not chash_exp.empty:
        c1, c2 = st.columns(2)
        with c1:
            sec("10 הוצאות מובילות", meta="לפי קטגוריה")
            top_cat = chash_exp.groupby("category")["amount"].sum().nlargest(10).round(0).reset_index()
            top_cat.columns = ["קטגוריה", "סה\"כ (₪)"]
            display_dataframe(top_cat, use_container_width=True, hide_index=True)
        with c2:
            sec("10 ספקים מובילים", meta="לפי סכום")
            top_sup = (chash_exp[chash_exp["supplier"].fillna("") != ""]
                        .groupby("supplier")["amount"].sum().nlargest(10).round(0).reset_index())
            top_sup.columns = ["ספק", "סה\"כ (₪)"]
            display_dataframe(top_sup, use_container_width=True, hide_index=True)
            from ui.pages.detail_view import drill_launcher
            drill_launcher("supplier", top_sup["ספק"].tolist(),
                            label="פתח פירוט ספק", key_suffix="overview")

    # ── Drill-Down לחודש (מהסקירה) ──
    if "month" in df.columns and df["month"].notna().any():
        from ui.pages.detail_view import drill_launcher
        months_avail = sorted(df["month"].dropna().unique())
        sec("פירוט לפי חודש", meta="בחר חודש לפירוט מלא")
        drill_launcher("month", months_avail,
                        label="פתח פירוט חודש", key_suffix="overview")

    # ── Drill-Down: מה מרכיב את הסכומים? ──────────────────────
    sec("🔍 פירוט מלא לכל מדד",
        meta="בחר מדד לראות את התנועות שמרכיבות אותו")
    chash_all = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    if chash_all.empty:
        st.caption("אין נתונים לפירוט.")
        return

    from core.chashbashevet_loader import real_income_mask
    DRILL_OPTIONS = [
        ("— בחר —", None),
        ("💰 כל ההכנסות", lambda d: d[real_income_mask(d)]),
        ("💸 כל ההוצאות", lambda d: d[(d["amount"] > 0) & (~real_income_mask(d))]),
        ("⛽ סה\"כ דלק ואנרגיה", lambda d: d[d.get("main_category", d.get("category", "")) == "דלק ואנרגיה"]),
        ("👷 סה\"כ שכר עבודה", lambda d: d[d.get("main_category", d.get("category", "")) == "שכר עבודה"]),
        ("🏢 סה\"כ קבלני משנה", lambda d: d[d.get("main_category", d.get("category", "")) == "קבלני משנה"]),
        ("🔧 סה\"כ אחזקת כלים", lambda d: d[d.get("main_category", d.get("category", "")) == "אחזקת כלים"]),
        ("🏗️ סה\"כ תשתיות", lambda d: d[d.get("main_category", d.get("category", "")) == "תשתיות"]),
        ("🚮 סה\"כ פינוי פסולת", lambda d: d[d.get("main_category", d.get("category", "")) == "פינוי פסולת"]),
        ("📊 סה\"כ ניהול ופיקוח", lambda d: d[d.get("main_category", d.get("category", "")) == "ניהול ופיקוח"]),
    ]
    pick = st.selectbox(
        "בחר מדד", [o[0] for o in DRILL_OPTIONS],
        key=f"overview_drill_{summary.get('months', ['x'])[0] if summary.get('months') else 'x'}",
    )
    if pick and pick != "— בחר —":
        filt = next(f for (label, f) in DRILL_OPTIONS if label == pick)
        if filt is None:
            return
        result = filt(chash_all)
        _render_tx_detail(result, title=pick, key_prefix=f"overview_{pick}",
                            file_basename="overview_drill")


# ─── Tab 2: הכנסות (חשבוניות-לרמת-פירוט) ────────────────────
import re as _re

_INVOICE_NUM_RE = _re.compile(r"(?:חשבונית|חש\"מ|חש'?\s*מס|אסמכתא)\s*[#:]?\s*(\d{3,})")


def _extract_invoice_num(description: str) -> str:
    """מנסה לחלץ מספר חשבונית מתוך 'פרטים'."""
    if not isinstance(description, str):
        return ""
    m = _INVOICE_NUM_RE.search(description)
    if m:
        return m.group(1)
    # fallback: מספר 4+ ספרות בודד בתחילת/באמצע ה-string
    m = _re.search(r"\b(\d{4,})\b", description)
    return m.group(1) if m else ""


def _tab_income(df: pd.DataFrame) -> None:
    """הכנסות = רק 'הכנסות פרויקט' ו'הכנסות חיוב ספק'.

    משתמש ב-real_income_mask המרכזי — אותה הגדרה בדיוק כמו ב-KPIs
    של מסך הסקירה ושל רשימת הפרויקטים. כך הסכומים מסונכרנים.
    """
    from core.chashbashevet_loader import real_income_mask
    if "source" in df.columns:
        chash = df[df["source"] == "chashbashevet"]
    else:
        chash = df

    income_all = chash[real_income_mask(chash)]

    if income_all.empty:
        ins("blue", "ℹ️", "אין הכנסות מתועדות",
            "מוצגות אך ורק 'הכנסות פרויקט' ו'הכנסות חיוב ספק'. "
            "ודא שהמאזן/כרטיס ההנהלה כולל אותן.")
        return

    # סה"כ הכנסות: amount שלילי = הכנסה (אחרי inversion ב-loader)
    total = float(income_all.loc[income_all["amount"] < 0, "amount"].sum() * -1
                  + income_all.loc[income_all["amount"] > 0, "amount"].sum())
    num_inv = int(len(income_all))
    c1, c2, c3 = st.columns(3)
    c1.metric("סה\"כ הכנסות", _fmt_money(total))
    c2.metric("מספר חשבוניות", str(num_inv))
    if "month" in income_all.columns and not income_all.empty:
        n_months = income_all["month"].nunique()
        c3.metric("ממוצע חודשי", _fmt_money(total / n_months) if n_months else "—")

    # ── חשבוניות לפי חודש ──
    sec("הכנסות לפי חודש")
    if "month" in income_all.columns:
        monthly = income_all.groupby("month")["amount"].sum().abs().reset_index()
        monthly.columns = ["חודש", "סכום"]
        monthly["סכום"] = monthly["סכום"].round(0)
        display_dataframe(monthly, use_container_width=True, hide_index=True)

    # ── טבלת חשבוניות עם date/customer/invoice#/amount/status ──
    sec("פירוט חשבוניות מכירה")
    invoice_df = income_all.copy()
    invoice_df["amount_abs"] = invoice_df["amount"].abs()
    if "description" in invoice_df.columns:
        invoice_df["invoice_num"] = invoice_df["description"].apply(_extract_invoice_num)
    else:
        invoice_df["invoice_num"] = ""
    invoice_df["status"] = "—"  # placeholder - דורש מעקב גבייה חיצוני

    show_cols = []
    rename_map = {}
    for src, heb in [
        ("date", "תאריך"),
        ("supplier", "לקוח"),
        ("invoice_num", "מס' חשבונית"),
        ("amount_abs", "סכום (₪)"),
        ("month", "חודש"),
        ("status", "סטטוס גבייה"),
        ("description", "פרטים"),
    ]:
        if src in invoice_df.columns:
            show_cols.append(src)
            rename_map[src] = heb

    disp = invoice_df[show_cols].copy()
    if "amount_abs" in disp.columns:
        disp["amount_abs"] = disp["amount_abs"].round(0)
    disp = disp.sort_values("date" if "date" in show_cols else show_cols[0])
    disp.columns = [rename_map[c] for c in show_cols]
    display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── 🔍 פירוט לקוח ──
    if "supplier" in income_all.columns:
        customers = sorted(income_all["supplier"].dropna()
                             .replace("", pd.NA).dropna().unique().tolist())
        if customers:
            from ui.pages.detail_view import drill_launcher
            drill_launcher("customer", customers,
                            label="פתח פירוט לקוח", key_suffix="income_tab")

    ins("blue", "ℹ️", "סטטוס גבייה",
        "סטטוס שולם/פתוח לא מנוטר אוטומטית מכרטיס ההנהלה. לתצוגה מלאה - "
        "חבר קובץ גבייה ייעודי או מערכת ניהול לקוחות.")

    # ── Drill-Down: לפי חשבון / לקוח / חודש ──
    sec("🔍 פירוט - בחר ממד")
    drill_by = st.radio(
        "ממד לפירוט", ["חשבון הכנסה", "לקוח", "חודש"],
        horizontal=True, key="income_drill_dim",
    )
    if drill_by == "חשבון הכנסה" and "account_name" in income_all.columns:
        accts = sorted(income_all["account_name"].dropna().unique().tolist())
        pick = st.selectbox("בחר חשבון", ["— בחר —"] + accts, key="income_drill_acct")
        if pick != "— בחר —":
            _render_tx_detail(income_all[income_all["account_name"] == pick],
                                title=pick, key_prefix=f"income_acct_{pick[:20]}",
                                file_basename="income_by_account")
    elif drill_by == "לקוח" and "supplier" in income_all.columns:
        clients = sorted(income_all[income_all["supplier"].fillna("") != ""]
                          ["supplier"].dropna().unique().tolist())
        if not clients:
            st.caption("אין לקוחות מזוהים.")
        else:
            pick = st.selectbox("בחר לקוח", ["— בחר —"] + clients, key="income_drill_cli")
            if pick != "— בחר —":
                _render_tx_detail(income_all[income_all["supplier"] == pick],
                                    title=pick, key_prefix=f"income_cli_{pick[:20]}",
                                    file_basename="income_by_client")
    elif drill_by == "חודש" and "month" in income_all.columns:
        months = sorted(income_all["month"].dropna().unique().tolist())
        pick = st.selectbox("בחר חודש", ["— בחר —"] + months, key="income_drill_month")
        if pick != "— בחר —":
            _render_tx_detail(income_all[income_all["month"] == pick],
                                title=pick, key_prefix=f"income_month_{pick}",
                                file_basename="income_by_month")


# ─── Tab 3: הוצאות (עם drill-down) ──────────────────────────
def _tab_expenses(df: pd.DataFrame) -> None:
    sec("הוצאות לפי קטגוריה")
    # רק חשבשבת ורק חיובי (הוצאות בפועל)
    exp_df = df[(df["source"] == "chashbashevet")] if "source" in df.columns else df.iloc[0:0]
    exp_df = exp_df[exp_df["amount"] > 0] if "amount" in exp_df.columns else exp_df

    if exp_df.empty:
        ins("blue", "ℹ️", "אין הוצאות מתועדות", "טען קובץ כרטיס הנהלה לחודש.")
        return

    # ── סיכום עליון ──
    total_exp = float(exp_df["amount"].sum())
    st.metric("סה\"כ הוצאות בפרויקט", _fmt_money(total_exp))

    # ── חלוקה לקטגוריות לפי מילות מפתח + "אחר" לכל מה שלא נופל ──
    buckets: dict[str, pd.DataFrame] = {}
    matched_indices: set = set()
    for label, keywords in KEYWORD_CATEGORIES.items():
        if label == "income":
            continue
        sub = _filter_by_keywords(exp_df, keywords)
        if not sub.empty:
            buckets[label] = sub
            matched_indices.update(sub.index.tolist())

    # שורות שלא תפסו אף קטגוריה
    other = exp_df[~exp_df.index.isin(matched_indices)]
    if not other.empty:
        buckets["other"] = other

    # ── טבלת סיכום ──
    summary_rows = []
    for label, sub in buckets.items():
        s = float(sub["amount"].sum())
        summary_rows.append({
            "קטגוריה": _label_he(label),
            "סכום (₪)": round(s, 0),
            "תנועות": int(len(sub)),
            "% מסך": round(s / total_exp * 100, 1) if total_exp else 0,
            "_key": label,
        })
    summary_rows.sort(key=lambda r: -r["סכום (₪)"])
    summary_df = pd.DataFrame(summary_rows).drop(columns=["_key"])
    display_dataframe(summary_df, use_container_width=True, hide_index=True)

    # ── Drill-down: expander לכל קטגוריה ──
    sec("פירוט תנועות לכל קטגוריה", meta="לחץ על קטגוריה לפתיחה")
    for row in summary_rows:
        label_he = row["קטגוריה"]
        key = row["_key"]
        sub = buckets[key]
        with st.expander(
            f"{label_he} — {_fmt_money(row['סכום (₪)'])} · {row['תנועות']} תנועות",
            expanded=False,
        ):
            cols = [c for c in ["date", "account_num", "account_name", "supplier",
                                "description", "debit", "credit", "amount", "month"]
                    if c in sub.columns]
            disp = sub[cols].copy().sort_values("date" if "date" in cols else cols[0])
            heb_names = {
                "date": "תאריך", "account_num": "חשבון", "account_name": "שם חשבון",
                "supplier": "ספק", "description": "פרטים",
                "debit": "חובה", "credit": "זכות", "amount": "סכום", "month": "חודש",
            }
            disp.columns = [heb_names.get(c, c) for c in disp.columns]
            display_dataframe(disp, use_container_width=True, hide_index=True)


# ─── Tab 4: עובדים ושכר (עם site_tracking) ──────────────────
def _tab_employees(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    from pipeline import load_site_tracking_data
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None

    # Top: salary cost from chashbashevet (כספי)
    salary_df = _filter_by_keywords(df, KEYWORD_CATEGORIES["salary"])
    if "amount" in salary_df.columns:
        salary_df = salary_df[salary_df["amount"] > 0]
    total_salary = float(salary_df["amount"].sum()) if "amount" in salary_df.columns and not salary_df.empty else 0

    # Per-employee daily hours from site_tracking (תפעולי)
    site_data = load_site_tracking_data(project_id) if project_id else {}
    emp_hours = site_data.get("employees_hours", pd.DataFrame())

    cA, cB, cC = st.columns(3)
    cA.metric("עלות שכר בפרויקט", _fmt_money(total_salary))
    if not emp_hours.empty and "name" in emp_hours.columns:
        cB.metric("עובדים פעילים", str(emp_hours["name"].nunique()))
        if "work_hours" in emp_hours.columns:
            cC.metric("סה\"כ שעות עבודה", f"{emp_hours['work_hours'].sum():,.0f}")

    # ── חלוקה לפי חשבון שכר (כספי) ──
    sec("חלוקה לפי חשבון שכר")
    if salary_df.empty:
        st.caption("אין נתוני חשבונות שכר בכרטיס ההנהלה.")
    else:
        by_acct = salary_df.groupby("account_name")["amount"].agg(["sum", "count"]).reset_index()
        by_acct.columns = ["חשבון", "סכום", "תנועות"]
        by_acct["סכום"] = by_acct["סכום"].round(0)
        display_dataframe(by_acct.sort_values("סכום", ascending=False),
                     use_container_width=True, hide_index=True)

    # ── רמת עובד בודד (מ-site_tracking) ──
    sec("עובדים - שעות יומיות", meta="מקובץ יומן שטח")
    if emp_hours.empty:
        ins("blue", "ℹ️", "אין נתוני שעות עובדים", "הוסף קובץ יומן שטח עם גליון 'שעות עבודה עובדים'.")
    else:
        per_emp = emp_hours.groupby("name").agg(
            ימי_עבודה=("date", "nunique"),
            סה_כ_שעות=("work_hours", "sum"),
        ).reset_index().sort_values("סה_כ_שעות", ascending=False)
        per_emp["סה_כ_שעות"] = per_emp["סה_כ_שעות"].round(1)
        per_emp.columns = ["שם עובד", "ימי עבודה", "סה\"כ שעות"]
        display_dataframe(per_emp, use_container_width=True, hide_index=True)

        # Drill-down per employee
        with st.expander("פירוט יומי לכל עובד"):
            cols = [c for c in ["date", "name", "start_time", "end_time",
                                "work_hours", "notes"] if c in emp_hours.columns]
            heb = {"date": "תאריך", "name": "שם", "start_time": "התחלה",
                   "end_time": "סיום", "work_hours": "שעות", "notes": "הערות"}
            disp = emp_hours[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── הזנות ידניות מ-SQLite ──
    if project_meta:
        sec("הזנות ידניות", meta="מטאב 'עדכון נתוני שטח'")
        from core import control_db
        manual = control_db.list_rows("employee_work_logs", project_meta["project_id"])
        if manual.empty:
            st.caption("אין הזנות ידניות. עבור לטאב 'עדכון נתוני שטח' כדי להוסיף.")
        else:
            agg = manual.groupby("employee_name").agg(
                ימי=("date", "nunique"),
                שעות=("hours", "sum"),
                ימים=("days", "sum"),
            ).reset_index().round(1)
            agg.columns = ["שם עובד", "ימי עבודה", "סה\"כ שעות", "סה\"כ ימים"]
            display_dataframe(agg, use_container_width=True, hide_index=True)


# ─── Tab 5: ספקים וקבלנים (עם site_tracking + סיווג) ───────
def _tab_suppliers(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    from pipeline import load_site_tracking_data
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None

    # ── 1. Top ספקים עם קטגוריה דומיננטית ──
    sec("30 ספקים מובילים - עם קטגוריה אוטומטית")
    sup_cat = project_aggregator.suppliers_categorized(df, top_n=30)
    if sup_cat.empty:
        ins("blue", "ℹ️", "אין ספקים מתועדים", "ספקים מחולצים מ-'פרטים' בכרטיס ההנהלה.")
    else:
        disp = sup_cat.copy()
        disp.columns = ["ספק", "קטגוריה ראשית", "סה\"כ (₪)", "תנועות",
                        "מס' קטגוריות", "קטגוריות משניות"]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── 2. ספקים לפי קטגוריה (טאבים פנימיים) ──
    sec("ספקים לפי קטגוריה")
    cat_groups = project_aggregator.suppliers_by_category(df)
    if not cat_groups:
        st.caption("אין נתונים מקוטלגים.")
    else:
        # Sort categories by total amount
        cat_sorted = sorted(cat_groups.items(),
                              key=lambda kv: -kv[1]["total_amount"].sum())
        cat_labels = [f"{c} ({int(len(g))})" for c, g in cat_sorted]
        cat_tabs = st.tabs(cat_labels)
        for tab, (cat_name, grp) in zip(cat_tabs, cat_sorted):
            with tab:
                t_amt = grp["total_amount"].sum()
                st.caption(f"סה\"כ {cat_name}: ₪{t_amt:,.0f} · {len(grp)} ספקים")
                show = grp[["supplier", "total_amount", "num_transactions"]].copy()
                show.columns = ["ספק", "סה\"כ (₪)", "תנועות"]
                display_dataframe(show, use_container_width=True, hide_index=True)

    sec("קבלני משנה - חיובים מחשבשבת")
    subs = _filter_by_keywords(df, KEYWORD_CATEGORIES["subcontractors"])
    if subs.empty:
        st.caption("לא זוהו תנועות תחת 'קבלני משנה'.")
    else:
        cols = [c for c in ["date", "supplier", "description", "amount"] if c in subs.columns]
        display_dataframe(subs[cols], use_container_width=True, hide_index=True)

    # ── קבלני משנה - שעות תפעוליות מ-site_tracking ──
    sec("קבלני משנה - שעות עבודה בשטח", meta="מקובץ יומן שטח")
    site_data = load_site_tracking_data(project_id) if project_id else {}
    sub_hours = site_data.get("subcontractors_hours", pd.DataFrame())
    if sub_hours.empty:
        st.caption("אין נתוני שעות קבלני משנה ביומן שטח.")
    else:
        per_sub = sub_hours.groupby("name").agg(
            ימי_עבודה=("date", "nunique"),
            סה_כ_שעות=("work_hours", "sum"),
        ).reset_index().sort_values("סה_כ_שעות", ascending=False)
        per_sub["סה_כ_שעות"] = per_sub["סה_כ_שעות"].round(1)
        per_sub.columns = ["שם קבלן/משאית", "ימי עבודה", "סה\"כ שעות"]
        display_dataframe(per_sub, use_container_width=True, hide_index=True)

        with st.expander("פירוט יומי לקבלני משנה"):
            cols = [c for c in ["date", "name", "license_num", "start_time",
                                "end_time", "work_hours", "notes"] if c in sub_hours.columns]
            heb = {"date": "תאריך", "name": "שם", "license_num": "מס' רכב",
                   "start_time": "התחלה", "end_time": "סיום",
                   "work_hours": "שעות", "notes": "הערות"}
            disp = sub_hours[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── הזנות ידניות מ-SQLite ──
    if project_meta:
        sec("הזנות ידניות")
        from core import control_db
        manual = control_db.list_rows("contractor_work_logs", project_meta["project_id"])
        if manual.empty:
            st.caption("אין הזנות ידניות. עבור לטאב 'עדכון נתוני שטח'.")
        else:
            cols = [c for c in ["date", "contractor_name", "work_type", "quantity",
                                "hours", "days", "price", "invoice_num", "notes"]
                    if c in manual.columns]
            heb = {"date": "תאריך", "contractor_name": "שם קבלן", "work_type": "סוג עבודה",
                   "quantity": "כמות", "hours": "שעות", "days": "ימים",
                   "price": "מחיר (₪)", "invoice_num": "מס' חשבונית", "notes": "הערות"}
            disp = manual[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)


# ─── Tab 6: סולר ואחזקה (מודול מלא) ─────────────────────────
def _tab_fuel_maintenance(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    # קניות סולר מחשבשבת (מילות מפתח: סולר/דלק)
    fuel_purchases = _filter_by_keywords(df, KEYWORD_CATEGORIES["fuel"])
    if "source" in fuel_purchases.columns:
        fuel_purchases = fuel_purchases[fuel_purchases["source"] == "chashbashevet"]
    if "amount" in fuel_purchases.columns:
        fuel_purchases = fuel_purchases[fuel_purchases["amount"] > 0]

    # ── KPIs עליונים ──
    total_liters = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0.0
    total_cost = float(fuel_purchases["amount"].sum()) if not fuel_purchases.empty else 0.0
    num_fuelings = int(len(solar))
    avg_price = total_cost / total_liters if total_liters > 0 else 0.0
    total_work_h = float(hours["work_hours"].sum()) if "work_hours" in hours.columns and not hours.empty else 0.0
    cost_per_hour = total_cost / total_work_h if total_work_h > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה\"כ ליטרים", f"{total_liters:,.0f}")
    c2.metric("סה\"כ עלות", _fmt_money(total_cost))
    c3.metric("₪ / ליטר", format_decimal(avg_price) if avg_price else "—")
    c4.metric("₪ / שעת עבודה", format_currency(cost_per_hour) if cost_per_hour else "—")
    st.caption(f"{num_fuelings} תדלוקים · {int(total_work_h):,} שעות עבודה")

    # ── מאזן מלאי (משלב fuel_inventory.xlsx אם קיים) ──
    sec("מאזן מלאי סולר", meta="מקובץ מלאי סולר")
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None
    inv_combined = _collect_fuel_inventory(project_id) if project_id else pd.DataFrame()

    if inv_combined.empty:
        st.markdown(
            f"""<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
            padding:14px 18px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
              <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
                letter-spacing:.8px;font-weight:700">מלאי פתיחה</div>
                <div style="font-size:18px;font-weight:800;color:#94A3B8">— ל'</div></div>
              <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
                letter-spacing:.8px;font-weight:700">+ קניות</div>
                <div style="font-size:18px;font-weight:800;color:var(--status-good)">
                  {total_liters:,.0f} ל'</div></div>
              <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
                letter-spacing:.8px;font-weight:700">− שימושים</div>
                <div style="font-size:18px;font-weight:800;color:var(--status-bad)">
                  {total_liters:,.0f} ל'</div></div>
              <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
                letter-spacing:.8px;font-weight:700">= מלאי סגירה</div>
                <div style="font-size:18px;font-weight:800;color:#94A3B8">— ל'</div></div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.caption("אין קובץ מלאי סולר. הוסף קובץ עם עמודות "
                   "<code>חודש / מלאי פתיחה (ל') / מלאי סגירה (ל')</code> "
                   "כדי לראות מאזן מלאי מלא.")
    else:
        # liters per month
        liters_per_month_purchases = {}
        if not fuel_purchases.empty and avg_price > 0 and "month" in fuel_purchases.columns:
            for m, grp in fuel_purchases.groupby("month"):
                liters_per_month_purchases[m] = float(grp["amount"].sum()) / avg_price
        usage_per_month = {}
        if not solar.empty and "month" in solar.columns:
            for m, grp in solar.groupby("month"):
                usage_per_month[m] = float(grp["liters"].sum())

        from core.fuel_inventory import compute_balance
        balance = compute_balance(inv_combined, liters_per_month_purchases, usage_per_month)
        if balance.empty:
            st.caption("מאזן ריק.")
        else:
            disp = balance.copy()
            disp.columns = ["חודש", "פתיחה (ל')", "קניות (ל')", "שימושים (ל')",
                            "סגירה צפויה (ל')", "סגירה בפועל (ל')",
                            "הפרש (ל')", "סטטוס"]
            display_dataframe(disp, use_container_width=True, hide_index=True)
            n_bad = int((balance["status"] == "חוסר").sum())
            if n_bad:
                ins("amber", "⚠️", f"{n_bad} חודשים עם חוסר במלאי",
                    "ההפרש מצביע על שימוש לא מתועד או פחת חריג.")

    # ── קניות סולר לפי ספק ──
    sec("קניות סולר לפי ספק")
    if fuel_purchases.empty:
        st.caption("לא זוהו רכישות סולר בכרטיס ההנהלה (חשבונות עם 'סולר'/'דלק').")
    else:
        by_sup = fuel_purchases.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_sup.columns = ["ספק", "סה\"כ (₪)", "חשבוניות"]
        by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
        display_dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט חשבוניות סולר"):
            fp = fuel_purchases.copy()
            if "description" in fp.columns:
                fp["invoice_num"] = fp["description"].apply(_extract_invoice_num)
            cols = [c for c in ["date", "supplier", "invoice_num", "description",
                                "amount", "month"] if c in fp.columns]
            disp = fp[cols].copy().sort_values("date" if "date" in cols else cols[0])
            heb = {"date": "תאריך", "supplier": "ספק", "invoice_num": "מס' חשבונית",
                   "description": "פרטים", "amount": "סכום (₪)", "month": "חודש"}
            disp.columns = [heb.get(c, c) for c in cols]
            if "סכום (₪)" in disp.columns:
                disp["סכום (₪)"] = disp["סכום (₪)"].round(0)
            display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── צריכה לפי רכב/כלי ──
    sec("צריכה לפי כלי", meta="מדוח תדלוקים")
    if solar.empty:
        ins("blue", "ℹ️", "אין נתוני תדלוק", "טען דוח תדלוקים לחודש.")
    else:
        by_tool = solar.groupby(["license_num", "tool_name"])["liters"].agg(
            ["sum", "count"]
        ).reset_index()
        by_tool.columns = ["מס' רישוי", "שם כלי", "סה\"כ ליטרים", "תדלוקים"]
        by_tool["סה\"כ ליטרים"] = by_tool["סה\"כ ליטרים"].round(0)

        # הוסף עלות משוערת (משערך לפי avg_price)
        if avg_price > 0:
            by_tool["עלות משוערת (₪)"] = (by_tool["סה\"כ ליטרים"] * avg_price).round(0)
        display_dataframe(by_tool.sort_values("סה\"כ ליטרים", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט תדלוקים"):
            cols = [c for c in ["date", "tool_name", "license_num", "liters",
                                "engine_hours", "lph_calculated"]
                    if c in solar.columns]
            display_dataframe(solar[cols].sort_values("date"),
                         use_container_width=True, hide_index=True)

    # ── תדלוקים ללא שעות עבודה (חשד) ──
    sec("תדלוקים ללא שעות עבודה (חשד לבזבוז)")
    from core import solar_loader, hours_loader
    from pipeline import _load_tools_registry
    if not solar.empty:
        sm = solar_loader.aggregate_by_tool_month(solar)
        hm = hours_loader.aggregate_by_tool_month(hours) if not hours.empty else pd.DataFrame(
            columns=["license_num", "month", "total_work_hours"]
        )
        no_hrs = anomaly_detector.detect_solar_without_hours(sm, hm, _load_tools_registry())
        if no_hrs.empty:
            ins("green", "✓", "כל הכלים שתודלקו אכן עבדו", "אין תדלוקים יתומים.")
        else:
            disp = no_hrs.copy()
            disp["estimated_waste_nis"] = disp["estimated_waste_nis"].round(0)
            disp.columns = ["מס' רישוי", "שם כלי", "סוג כלי", "חודש",
                            "סה\"כ ליטרים", "בזבוז משוער (₪)"]
            display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── מה דורש קלט חיצוני ──
    with st.expander("💡 מה דורש קלט חיצוני להשלמת המודול"):
        st.markdown("""
        - **מלאי פתיחה/סגירה**: דורש `fuel_inventory.xlsx` ידני
          עם עמודות `month, opening_l, closing_l`.
        - **שיוך נהג/מפעיל לתדלוק**: לא קיים בקובץ solar.xlsx של Pointer.
          ניתן להוסיף עמודה `driver` אם המערכת התפעולית שלך תומכת.
        - **שיוך ק"מ (לרכבים)**: כרגע יש רק `engine_hours` (לכלי צמ"ה).
          אם המזכירה מתעדת ק"מ לרכבים - להוסיף עמודה `kilometers`.
        """)

    # ── אחזקות ──
    sec("אחזקות - מוסך, תיקונים, חלפים")
    maint = _filter_by_keywords(df, KEYWORD_CATEGORIES["maintenance"])
    if "source" in maint.columns:
        maint = maint[maint["source"] == "chashbashevet"]
    if "amount" in maint.columns:
        maint = maint[maint["amount"] > 0]
    if maint.empty:
        st.caption("אין תנועות תחת מילות מפתח 'אחזקת', 'מוסך', 'תיקונים'.")
    else:
        total_m = float(maint["amount"].sum())
        st.metric("סה\"כ אחזקה", _fmt_money(total_m))
        by_supm = maint.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_supm.columns = ["ספק / מוסך", "סה\"כ (₪)", "תנועות"]
        by_supm["סה\"כ (₪)"] = by_supm["סה\"כ (₪)"].round(0)
        display_dataframe(by_supm.sort_values("סה\"כ (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט תנועות אחזקה"):
            cols = [c for c in ["date", "month", "account_name", "supplier",
                                "description", "amount"] if c in maint.columns]
            display_dataframe(maint[cols].sort_values("date" if "date" in cols else cols[0]),
                         use_container_width=True, hide_index=True)

    # ── הזנות ידניות: יומן סולר + אחזקה ──
    if project_meta:
        from core import control_db
        sec("יומן סולר ידני")
        fl = control_db.list_rows("fuel_logs", project_meta["project_id"])
        if fl.empty:
            st.caption("אין הזנות ידניות של תדלוקים.")
        else:
            cols = [c for c in ["date", "tool_name", "license_num", "driver", "supplier",
                                "invoice_num", "liters", "price_per_liter", "total_cost",
                                "notes"] if c in fl.columns]
            heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
                   "driver": "נהג", "supplier": "ספק", "invoice_num": "חשבונית",
                   "liters": "ל'", "price_per_liter": "₪/ל'", "total_cost": "סה\"כ ₪",
                   "notes": "הערות"}
            disp = fl[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)
            t_l = float(fl["liters"].sum()) if "liters" in fl.columns else 0
            t_c = float(fl["total_cost"].sum()) if "total_cost" in fl.columns else 0
            st.caption(f"סה\"כ ידני: {t_l:,.0f} ל' / ₪{t_c:,.0f}")


# ─── Tab 7: רכבים וכלים (מאוחד) ─────────────────────────────
def _tab_vehicles_tools(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    """תצוגה מאוחדת לכל כלי: רישוי, סוג, שעות, סולר, עלות משוערת, ניצול."""
    from pipeline import _load_tools_registry

    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
    tools_reg = _load_tools_registry()

    # חישוב מחיר ממוצע לליטר מתוך חשבשבת (לעלות סולר משוערת לכלי)
    fuel_chash = _filter_by_keywords(chash, KEYWORD_CATEGORIES["fuel"])
    if "amount" in fuel_chash.columns:
        fuel_chash = fuel_chash[fuel_chash["amount"] > 0]
    total_fuel_cost = float(fuel_chash["amount"].sum()) if not fuel_chash.empty else 0.0
    total_liters_all = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0.0
    avg_lp = total_fuel_cost / total_liters_all if total_liters_all > 0 else 0.0

    # בדיקה אם יש שיוכים ידניים — אם כן, נציג גם אם solar/hours ריקים
    manual_assignments_exist = False
    if project_meta:
        try:
            from core import fuel_assignments
            manual_costs = fuel_assignments.fuel_cost_per_license(
                project_meta["project_id"], df,
            )
            manual_assignments_exist = not manual_costs.empty
        except Exception:
            pass

    if hours.empty and solar.empty and not manual_assignments_exist:
        ins("blue", "ℹ️", "אין נתוני כלים",
            "טען דוח שעות עבודה ו/או דוח תדלוקים, או שייך תנועות דלק "
            "מטאב '🔧 התאמת דלק' בסולר.")
        return

    # ── אגרגציה מאוחדת לכל כלי ──
    # שעות לפי license_num
    if not hours.empty:
        by_h = hours.groupby("license_num").agg(
            tool_name=("tool_name", lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
            total_hours=("work_hours", "sum"),
            work_days=("date", "nunique"),
        ).reset_index()
    else:
        by_h = pd.DataFrame(columns=["license_num", "tool_name", "total_hours", "work_days"])

    # סולר לפי license_num
    if not solar.empty:
        by_s = solar.groupby("license_num").agg(
            tool_name_s=("tool_name", lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
            total_liters=("liters", "sum"),
            fueling_count=("liters", "size"),
        ).reset_index()
    else:
        by_s = pd.DataFrame(columns=["license_num", "tool_name_s", "total_liters", "fueling_count"])

    # מיזוג שני המקורות
    merged = by_h.merge(by_s, on="license_num", how="outer")
    merged["tool_name"] = merged["tool_name"].fillna("").replace("", pd.NA)
    merged["tool_name"] = merged["tool_name"].fillna(merged.get("tool_name_s", ""))
    merged = merged.drop(columns=[c for c in ["tool_name_s"] if c in merged.columns])
    for col in ("total_hours", "total_liters", "fueling_count", "work_days"):
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    # הוסף נתוני tools_registry (סוג כלי + תקן עליון)
    if not tools_reg.empty:
        reg_cols = ["license_num", "tool_type", "norm_high"]
        reg_cols = [c for c in reg_cols if c in tools_reg.columns]
        merged = merged.merge(tools_reg[reg_cols], on="license_num", how="left")
    if "tool_type" not in merged.columns:
        merged["tool_type"] = "—"

    # חישובים נגזרים
    merged["lph_actual"] = merged.apply(
        lambda r: round(r["total_liters"] / r["total_hours"], 1)
        if r["total_hours"] > 0 else 0, axis=1)
    merged["fuel_cost_est"] = (merged["total_liters"] * avg_lp).round(0) if avg_lp > 0 else 0
    merged["over_norm"] = merged.apply(
        lambda r: "⚠️" if r.get("norm_high") and r["lph_actual"] > r["norm_high"] * 1.15
        else ("✓" if r["total_hours"] > 0 else "—"),
        axis=1
    )

    # ── עלות דלק משויכת ידנית (מ-chashbashevet, דרך טאב התאמת דלק) ──
    if project_meta:
        from core import fuel_assignments
        manual_costs = fuel_assignments.fuel_cost_per_license(
            project_meta["project_id"], df,
        )
        if not manual_costs.empty:
            # אם יש license_num שמופיע רק במשויכים ידנית (לא ב-solar/hours)
            # — צריך להוסיף אותו כשורה חדשה ל-merged לפני המיזוג.
            new_lics = set(manual_costs["license_num"].astype(int)) - \
                       set(merged["license_num"].dropna().astype(int)) \
                       if not merged.empty else set(manual_costs["license_num"].astype(int))
            if new_lics:
                tools_idx = tools_reg.set_index("license_num", drop=False) \
                    if not tools_reg.empty and "license_num" in tools_reg.columns \
                    else pd.DataFrame()
                add_rows = []
                for lic in new_lics:
                    tname = ""
                    if not tools_idx.empty and lic in tools_idx.index:
                        tname = str(tools_idx.loc[lic].get("tool_name", "") or "")
                    add_rows.append({
                        "license_num": lic, "tool_name": tname,
                        "total_hours": 0, "work_days": 0,
                        "total_liters": 0, "fueling_count": 0,
                    })
                merged = pd.concat([merged, pd.DataFrame(add_rows)],
                                      ignore_index=True, sort=False)
                # מילוי norm_high מהמירשם
                if not tools_reg.empty and "norm_high" in tools_reg.columns:
                    merged = merged.drop(columns=[c for c in ("norm_high", "tool_type") if c in merged.columns])
                    reg_cols = [c for c in ("license_num", "tool_type", "norm_high")
                                 if c in tools_reg.columns]
                    merged = merged.merge(tools_reg[reg_cols], on="license_num", how="left")

            merged = merged.merge(manual_costs, on="license_num", how="left")
            merged["assigned_fuel_cost"] = merged["assigned_fuel_cost"].fillna(0)
            merged["n_assigned_tx"] = merged["n_assigned_tx"].fillna(0).astype(int)
        else:
            merged["assigned_fuel_cost"] = 0
            merged["n_assigned_tx"] = 0
    else:
        merged["assigned_fuel_cost"] = 0
        merged["n_assigned_tx"] = 0

    # ── עלות סולר כוללת = עלות משוערת + שיוכים ידניים ──
    merged["fuel_cost_total"] = (
        merged["fuel_cost_est"].fillna(0) + merged["assigned_fuel_cost"].fillna(0)
    ).round(0)
    # ל'/ש' מבחינת עלות (₪/שעה)
    merged["cost_per_hour"] = merged.apply(
        lambda r: round(r["fuel_cost_total"] / r["total_hours"], 1)
        if r["total_hours"] > 0 else 0, axis=1,
    )

    # ── תצוגה מאוחדת ──
    sec("כל הכלים בפרויקט")
    n_tools = int(merged["license_num"].nunique())
    total_h = float(merged["total_hours"].sum())
    total_l = float(merged["total_liters"].sum())
    total_manual = float(merged["assigned_fuel_cost"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("כלים פעילים", format_number(n_tools))
    c2.metric("סה\"כ שעות", format_number(total_h))
    c3.metric("סה\"כ ליטרים", format_number(total_l))
    c4.metric("עלות סולר כוללת",
              format_currency(merged["fuel_cost_total"].sum()),
              delta=f"מזה {format_currency(total_manual)} משוייך ידנית"
              if total_manual else None)

    show_cols = ["license_num", "tool_name", "tool_type", "total_hours",
                 "work_days", "total_liters", "fueling_count",
                 "lph_actual", "norm_high",
                 "fuel_cost_est", "assigned_fuel_cost", "fuel_cost_total",
                 "cost_per_hour", "over_norm"]
    show_cols = [c for c in show_cols if c in merged.columns]
    disp = merged[show_cols].copy()
    disp["total_hours"] = disp["total_hours"].round(1)
    if "total_liters" in disp.columns:
        disp["total_liters"] = disp["total_liters"].round(0)
    heb = {
        "license_num":         "מס' רישוי",
        "tool_name":           "שם כלי",
        "tool_type":           "סוג",
        "total_hours":         "שעות",
        "work_days":           "ימי עבודה",
        "total_liters":        "ליטרים",
        "fueling_count":       "תדלוקים",
        "lph_actual":          "ל'/ש'",
        "norm_high":           "תקן",
        "fuel_cost_est":       "עלות סולר משוערת (₪)",
        "assigned_fuel_cost":  "₪ דלק משויך ידנית",
        "fuel_cost_total":     "סה\"כ עלות סולר (₪)",
        "cost_per_hour":       "₪ / שעה",
        "over_norm":           "מצב",
    }
    disp.columns = [heb.get(c, c) for c in show_cols]
    sort_col = "סה\"כ עלות סולר (₪)" if "סה\"כ עלות סולר (₪)" in disp.columns else disp.columns[0]
    display_dataframe(disp.sort_values(sort_col, ascending=False))

    # ── 🔍 פירוט כלי ──
    tool_options = merged["license_num"].dropna().astype(int).tolist()
    if tool_options:
        from ui.pages.detail_view import drill_launcher
        drill_launcher("tool", tool_options,
                        label="פתח פירוט כלי", key_suffix="tools_tab")

    # ── חריגות סולר ──
    sec("חריגות צריכת סולר", meta="ל'/ש' מעל תקן × 1.15")
    if not solar.empty and not hours.empty:
        from core import solar_loader, hours_loader
        sm = solar_loader.aggregate_by_tool_month(solar)
        hm = hours_loader.aggregate_by_tool_month(hours)
        excess = anomaly_detector.detect_solar_excess(sm, hm, tools_reg)
        if excess.empty:
            ins("green", "✓", "כל הכלים בתקן", "אין חריגות צריכת סולר.")
        else:
            disp = excess.copy()
            disp["actual_lph"] = disp["actual_lph"].round(1)
            disp["damage_estimate_nis"] = disp["damage_estimate_nis"].round(0)
            disp.columns = ["מס' רישוי", "שם כלי", "חודש", "סה\"כ ל'",
                            "סה\"כ שעות", "ל'/ש' בפועל", "תקן עליון",
                            "חריגה (ל')", "נזק (₪)", "חומרה"]
            display_dataframe(disp, use_container_width=True, hide_index=True)
    else:
        st.caption("נדרשים גם דוח תדלוקים וגם דוח שעות לזיהוי חריגות סולר.")

    # ── טיפולים ─ next service due (מ-site_tracking) ──
    from pipeline import load_site_tracking_data
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None
    site_data = load_site_tracking_data(project_id) if project_id else {}

    treatments = site_data.get("treatments", pd.DataFrame())
    if not treatments.empty:
        sec("מרווחי טיפול וטיפולים הבאים", meta="מיומן שטח")
        cols = [c for c in ["tool_name", "license_num", "owner",
                            "engine_hours_current", "engine_hours_last_service",
                            "last_service_date", "service_interval",
                            "next_service_hours", "hours_until_service"]
                if c in treatments.columns]
        heb = {"tool_name": "שם כלי", "license_num": "מס' רישוי", "owner": "בעלים",
               "engine_hours_current": "שעות נוכחיות",
               "engine_hours_last_service": "שעות בטיפול אחרון",
               "last_service_date": "תאריך טיפול",
               "service_interval": "מרווח טיפול",
               "next_service_hours": "שעות לטיפול הבא",
               "hours_until_service": "שעות נותרות"}
        disp = treatments[cols].copy()
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    log = site_data.get("treatments_log", pd.DataFrame())
    if not log.empty:
        sec("יומן טיפולים")
        display_dataframe(log, use_container_width=True, hide_index=True)

    fluids = site_data.get("other_fluids", pd.DataFrame())
    if not fluids.empty:
        sec("צריכת נוזלים אחרים", meta="אוריאה / שמן מנוע / שמן הידראולי")
        agg_cols = [c for c in ["urea_l", "engine_oil_l", "hydraulic_oil_l", "engine_oil_2_l"]
                    if c in fluids.columns]
        if agg_cols and "tool_name" in fluids.columns:
            per_tool = fluids.groupby(["license_num", "tool_name"])[agg_cols].sum().reset_index()
            per_tool[agg_cols] = per_tool[agg_cols].round(1)
            heb = {"license_num": "מס' רישוי", "tool_name": "שם כלי",
                   "urea_l": "אוריאה (ל')", "engine_oil_l": "שמן מנוע (ל')",
                   "hydraulic_oil_l": "שמן הידראולי (ל')",
                   "engine_oil_2_l": "שמן מנוע 2 (ל')"}
            per_tool.columns = [heb.get(c, c) for c in per_tool.columns]
            display_dataframe(per_tool, use_container_width=True, hide_index=True)

    # ── הזנות ידניות: שעות כלים + טיפולים ──
    if project_meta:
        from core import control_db
        pid = project_meta["project_id"]

        sec("שעות כלים ידני")
        eq = control_db.list_rows("equipment_work_logs", pid)
        if eq.empty:
            st.caption("אין הזנות ידניות של שעות עבודה לכלים.")
        else:
            cols = [c for c in ["date", "tool_name", "license_num", "operator",
                                "work_hours", "engine_hours", "notes"] if c in eq.columns]
            heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
                   "operator": "מפעיל", "work_hours": "ש\"ע", "engine_hours": "ש\"מ",
                   "notes": "הערות"}
            disp = eq[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)

        sec("טיפולים ידני")
        ml = control_db.list_rows("maintenance_logs", pid)
        if ml.empty:
            st.caption("אין הזנות ידניות של טיפולים.")
        else:
            cols = [c for c in ["date", "tool_name", "license_num", "treatment_type",
                                "garage_supplier", "cost", "engine_hours",
                                "next_service_hours", "invoice_num", "notes"]
                    if c in ml.columns]
            heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
                   "treatment_type": "סוג טיפול", "garage_supplier": "מוסך/ספק",
                   "cost": "עלות (₪)", "engine_hours": "ש\"מ",
                   "next_service_hours": "טיפול הבא", "invoice_num": "חשבונית",
                   "notes": "הערות"}
            disp = ml[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── הסבר על מה שחסר ──
    with st.expander("💡 מה שעוד דורש קלט חיצוני"):
        st.markdown("""
        - **תיקונים פר-כלי**: חשבשבת מציג אחזקה ברמת הפרויקט, לא פר רכב.
          לדיוק מלא נדרש שדה `license_num` בכל חשבונית תיקון.
        - **שיוך נהג/מפעיל**: לא קיים ב-`solar.xlsx` של Pointer/דלקן.
          ניתן להוסיף מ-`hours.xlsx` אם המזכירה מתעדת שם עובד.
        - **ניצול**: דורש "שעות זמינות" לכל כלי בחודש (לפי תקן 8 שעות × ימי עבודה).
        """)


# ─── Tab 8: פירוט תנועות ────────────────────────────────────
def _tab_transactions(df: pd.DataFrame) -> None:
    sec(f"כל התנועות ({len(df):,})")
    cols = [c for c in ["date", "month", "account_num", "account_name",
                        "supplier", "description", "amount", "source"]
            if c in df.columns]
    disp = df[cols].copy()

    # ── שורת פילטרים: חיפוש חופשי · מקור · טווח סכום ──
    fc1, fc2 = st.columns([3, 2])
    with fc1:
        q = st.text_input("🔍 חיפוש בתנועות", key="tx_search",
                          placeholder="חפש ספק / חשבון / פרטים…")
    with fc2:
        src_opts = ["הכול"]
        if "source" in disp.columns:
            src_opts += [_SOURCE_HE.get(s, s)
                         for s in disp["source"].dropna().unique()]
        src_pick = st.selectbox("מקור", src_opts, key="tx_src")

    # סינון לפי מקור
    if "source" in disp.columns and src_pick != "הכול":
        disp = disp[disp["source"].map(lambda s: _SOURCE_HE.get(s, s)) == src_pick]

    # סינון לפי טווח סכום
    if "amount" in disp.columns and not disp.empty:
        amounts = pd.to_numeric(disp["amount"], errors="coerce")
        lo, hi = float(amounts.min()), float(amounts.max())
        if lo < hi:
            rng = st.slider("טווח סכום (₪)", min_value=lo, max_value=hi,
                            value=(lo, hi), key="tx_amount_rng")
            disp = disp[(amounts >= rng[0]) & (amounts <= rng[1])]

    # חיפוש חופשי
    if q.strip():
        ql = q.strip().lower()
        mask = pd.Series(False, index=disp.index)
        for c in ("account_name", "supplier", "description", "account_num"):
            if c in disp.columns:
                mask |= disp[c].astype(str).str.lower().str.contains(ql, na=False)
        disp = disp[mask]

    st.caption(f"{len(disp):,} תנועות מוצגות")

    # תרגום ערכי 'source' לעברית
    if "source" in disp.columns:
        disp["source"] = disp["source"].map(_SOURCE_HE).fillna(disp["source"])

    # תרגום כותרות עמודות לעברית
    disp = _heb_columns(disp, _FULL_TX_COL_HEB)
    # המרת עמודות סכום ל-numeric כדי שפורמט הפסיקים יחול
    for c in ("סכום", "סכום (₪)", "חובה", "זכות", "נטו", "נטו (₪)"):
        if c in disp.columns:
            disp[c] = pd.to_numeric(disp[c], errors="coerce")
    display_dataframe(disp, use_container_width=True, hide_index=True,
                  column_config=build_column_config(disp.columns))
    _excel_download(disp, sheet_name="תנועות",
                     file_name="transactions.xlsx",
                     label="⬇️ ייצוא לאקסל", key="dl_all_tx")


_SOURCE_HE = {
    "chashbashevet": "כרטיס הנהלה",
    "solar": "תדלוקים",
    "hours": "שעות עבודה",
    "manual": "הזנה ידנית",
    "balance": "מאזן בוחן",
    "fuel_invoices": "חשבוניות דלק",
    "site_tracking": "יומן שטח",
}


# ─── עזר: איסוף fuel_inventory לכל חודשי הפרויקט ────────────
def _collect_fuel_inventory(project_id: str) -> pd.DataFrame:
    """קורא fuel_inventory.xlsx מכל החודשים של הפרויקט ומאחד."""
    from core.fuel_inventory import load_fuel_inventory
    from pipeline import PROJECTS_ROOT, list_available_months, _find_file

    frames = []
    for m in list_available_months(project_id):
        month_dir = PROJECTS_ROOT / project_id / m
        inv_path = _find_file(month_dir, ["fuel_inventory", "מלאי סולר", "מלאי"],
                              "fuel_inventory.xlsx")
        if inv_path:
            inv = load_fuel_inventory(inv_path)
            if not inv.empty:
                frames.append(inv)
    if not frames:
        return pd.DataFrame(columns=["month", "opening_l", "closing_l"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["month"])


def _tab_qa(df: pd.DataFrame, project_meta: dict) -> None:
    """דוחות איכות נתונים - מה חסר/חשוד/לא מסווג."""
    from core import categorizer, storage, month_locks
    from pipeline import list_available_months, PROJECTS_ROOT
    project_id = project_meta["project_id"]

    # ── ניהול נעילת חודשים ──
    sec("🔒 נעילת חודשים", meta="סגירת חודש נועלת את הנתונים מפני שינויים")
    months_avail = list_available_months(project_id)
    locked = month_locks.list_locks(project_id)
    locked_set = set(locked["month"].tolist()) if not locked.empty else set()

    mc1, mc2, mc3 = st.columns([2, 1, 1])
    with mc1:
        target_month = st.selectbox(
            "חודש לניהול נעילה",
            ["— בחר חודש —"] + list(months_avail),
            key=f"lock_month_pick_{project_id}",
        )
    if target_month and target_month != "— בחר חודש —":
        is_locked = target_month in locked_set
        with mc2:
            st.metric("סטטוס", "🔒 נעול" if is_locked else "🔓 פתוח")
        with mc3:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if not is_locked:
                if st.button("🔒 סגור חודש", key=f"lock_btn_{target_month}",
                               use_container_width=True):
                    ok, msg = month_locks.lock_month(
                        project_id, target_month,
                        locked_by="user",
                        notes=f"נסגר ידנית דרך מסך QA",
                    )
                    if ok:
                        st.success(f"✅ {msg}")
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                if st.button("🔓 פתח חודש מחדש",
                               key=f"unlock_btn_{target_month}",
                               use_container_width=True):
                    ok, msg = month_locks.unlock_month(
                        project_id, target_month, reason="פתיחה ידנית",
                    )
                    if ok:
                        st.success(f"✅ {msg}")
                        st.rerun()
    if not locked.empty:
        st.caption(f"חודשים נעולים: {', '.join(sorted(locked_set))}")
    st.markdown("---")

    # ── חריגות בטיפול (persisted) ──
    sec("חריגות במעקב", meta="מטבלת בעיות איכות נתונים")
    status_filter = st.radio(
        "סטטוס", ["פתוחות", "טופלו", "כל הסטטוסים"],
        horizontal=True, key=f"qa_status_{project_id}",
        label_visibility="collapsed",
    )
    status_map = {"פתוחות": "open", "טופלו": "resolved", "כל הסטטוסים": "all"}
    persisted = storage.list_quality_issues(project_id, status=status_map[status_filter])

    if persisted.empty:
        st.caption("אין חריגות במעקב. לחץ '💾 רשום' באחת מהבדיקות למטה כדי להעביר ממצאים לכאן.")
    else:
        # KPI
        cA, cB, cC = st.columns(3)
        cA.metric("פתוחות", str(int((persisted["status"] == "open").sum())))
        cB.metric("טופלו", str(int((persisted["status"] == "resolved").sum())))
        cC.metric("השפעה כספית פתוחה",
                  f"₪{persisted.loc[persisted['status']=='open','estimated_impact_nis'].sum():,.0f}")

        # תרגומים לעברית
        SEV_HE = {"high": "גבוה", "medium": "בינוני", "low": "נמוך"}
        STATUS_HE = {"open": "פתוח", "resolved": "טופל", "dismissed": "נדחה"}
        CHECK_HE = {
            "unmapped_account": "חשבון לא ממופה",
            "solar_excess": "חריגת סולר",
            "solar_without_hours": "סולר ללא שעות",
            "hours_excessive": "שעות מופרזות",
            "hours_negative": "שעות שליליות",
            "large_transaction": "תנועה גדולה",
            "suspicious_description": "תיאור חשוד",
            "unassigned_transaction": "תנועה לא משויכת",
        }

        # Show as expandable list with action buttons
        for _, row in persisted.head(20).iterrows():
            issue_id = int(row["id"])
            is_open = row["status"] == "open"
            icon = "🔴" if is_open else "✅"
            sev = SEV_HE.get(row.get("severity") or "", row.get("severity") or "—")
            check_he = CHECK_HE.get(row.get("check_type", ""), row.get("check_type", ""))
            status_he = STATUS_HE.get(row["status"], row["status"])
            impact = row.get("estimated_impact_nis") or 0
            label = f"{icon} {check_he} · {row['entity']} · ₪{impact:,.0f} ({sev})"

            with st.expander(label):
                st.write(f"**פרטים**: {row.get('details', '—')}")
                st.caption(f"חודש: {row.get('month', '—')} · "
                           f"נוצר: {row.get('created_at', '—')} · "
                           f"סטטוס: {status_he}")
                if row.get("notes"):
                    st.caption(f"הערות: {row['notes']}")

                if is_open:
                    c_r, c_d, c_n = st.columns([1, 1, 3])
                    with c_r:
                        if st.button("✅ סמן כטופל", key=f"resolve_{issue_id}",
                                     use_container_width=True):
                            storage.mark_issue_resolved(issue_id, notes="resolved")
                            st.success("סומן כטופל")
                            st.rerun()
                    with c_d:
                        if st.button("🚫 דחה", key=f"dismiss_{issue_id}",
                                     use_container_width=True):
                            import sqlite3
                            with sqlite3.connect(storage.DB_CONTROL) as conn:
                                conn.execute(
                                    "UPDATE data_quality_issues SET status='dismissed', "
                                    "updated_at=? WHERE id=?",
                                    [pd.Timestamp.now().isoformat(timespec="seconds"), issue_id],
                                )
                            st.info("נדחה")
                            st.rerun()

        if len(persisted) > 20:
            st.caption(f"מציג 20 מתוך {len(persisted)}.")

    st.markdown("---")
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]

    # ── סיכום מצב נתונים ──
    sec("מצב טעינת נתונים")
    project_id = project_meta["project_id"]
    months = list_available_months(project_id)
    rows = []
    for m in months:
        month_dir = PROJECTS_ROOT / project_id / m
        files = {f.name for f in month_dir.iterdir() if f.is_file()
                 and f.suffix.lower() in (".xlsx", ".xls") and not f.name.startswith("~$")}
        has_chash = any("כרטיס" in f or "chashbashevet" in f.lower() for f in files)
        has_solar = any("סולר" in f or "solar" in f.lower() or "תדלוק" in f for f in files)
        has_hours = any("שעות" in f or "hours" in f.lower() for f in files)
        has_bal = any("מאזן" in f or "balance" in f.lower() for f in files)
        chash_n = int(len(chash[chash["month"] == m])) if not chash.empty else 0
        rows.append({
            "חודש": m,
            "כרטיס הנהלה": "✓" if has_chash else "✗",
            "מאזן": "✓" if has_bal else "✗",
            "סולר": "✓" if has_solar else "✗",
            "שעות": "✓" if has_hours else "✗",
            "תנועות נטענו": chash_n,
        })
    if rows:
        display_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("אין חודשים בתיקיית הפרויקט.")

    # ── 1. תנועות שנפלו לקטגוריות fallback (אחר/הוצאות תפעוליות וכו') ──
    sec("חשבונות לא מקוטלגים")
    unmapped = categorizer.report_unmapped(chash)
    if unmapped.empty:
        ins("green", "✓", "כל החשבונות מקוטלגים", "אין שום חשבון בקטגוריית ברירת מחדל.")
    else:
        st.caption(f"{len(unmapped)} חשבונות. עדכן את category_mapping.xlsx כדי לסווג אותם נכון.")
        display_dataframe(unmapped, use_container_width=True, hide_index=True)
        col_dl, col_log = st.columns([2, 1])
        with col_dl:
            from io import BytesIO
            buf = BytesIO()
            unmapped.to_excel(buf, index=False, engine="openpyxl")
            st.download_button("⬇️ הורד unmapped_accounts.xlsx",
                               data=buf.getvalue(),
                               file_name="unmapped_accounts.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col_log:
            if st.button("💾 רשום למעקב", key="log_unmapped",
                         help="העברת כל החשבונות הלא ממופים לטבלת data_quality_issues"):
                n = 0
                for _, r in unmapped.iterrows():
                    storage.log_quality_issue(
                        project_id=project_id,
                        check_type="unmapped_account",
                        severity="medium",
                        entity=str(r.get("account_num", "")),
                        details=f"{r.get('account_name', '')}: {r.get('total_amount', 0):,.0f}₪",
                        estimated_impact=float(r.get("total_amount", 0)),
                    )
                    n += 1
                st.success(f"נרשמו {n} חשבונות למעקב")
                st.rerun()

    # ── 2. תנועות עם ספק ריק / חשוד ──
    sec("תנועות ללא ספק / פרטים ריקים")
    if "supplier" in chash.columns and not chash.empty:
        empty_sup = chash[
            (chash["supplier"].fillna("").astype(str).str.strip() == "") &
            (chash["amount"].abs() > 1000)
        ]
        if empty_sup.empty:
            ins("green", "✓", "אין", "כל החיובים המשמעותיים כוללים שם ספק.")
        else:
            st.caption(f"{len(empty_sup)} תנועות מעל ₪1000 ללא ספק זוהה.")
            cols = [c for c in ["date", "account_num", "account_name",
                                "description", "amount"] if c in empty_sup.columns]
            display_dataframe(empty_sup[cols], use_container_width=True, hide_index=True)

    # ── 3. כפילויות חשודות (אותו ספק, סכום, חודש) ──
    sec("כפילויות חשודות")
    if not chash.empty and "supplier" in chash.columns:
        dup_groups = chash[chash["supplier"].fillna("") != ""].groupby(
            ["supplier", "amount", "month"], dropna=False
        ).size().reset_index(name="כפילויות")
        dup_groups = dup_groups[dup_groups["כפילויות"] > 1].sort_values("כפילויות", ascending=False)
        if dup_groups.empty:
            ins("green", "✓", "אין כפילויות", "לא נמצאו שילובים (ספק+סכום+חודש) שמופיעים יותר מפעם אחת.")
        else:
            st.caption(f"{len(dup_groups)} שילובי (ספק, סכום, חודש) חוזרים. בדוק אם זה כפילות אמיתית או חיובים נפרדים.")
            disp = dup_groups.copy()
            disp.columns = ["ספק", "סכום (₪)", "חודש", "כפילויות"]
            disp["סכום (₪)"] = disp["סכום (₪)"].round(0)
            display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── 4. סולר ללא כלי / כלים ללא שעות ──
    sec("חוסרי שיוך - סולר ושעות")
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**תדלוקים בלי license_num**")
        if solar.empty:
            st.caption("אין נתוני סולר בכלל.")
        else:
            orphan_fuel = solar[solar["license_num"].isna()]
            if orphan_fuel.empty:
                ins("green", "✓", "אין", "כל התדלוקים שויכו לכלי.")
            else:
                display_dataframe(orphan_fuel[["date", "tool_name", "liters"]],
                             use_container_width=True, hide_index=True)
    with cB:
        st.markdown("**שעות עבודה בלי license_num**")
        if hours.empty:
            st.caption("אין נתוני שעות בכלל.")
        else:
            orphan_hrs = hours[hours["license_num"].isna()]
            if orphan_hrs.empty:
                ins("green", "✓", "אין", "כל השעות שויכו לכלי.")
            else:
                display_dataframe(orphan_hrs[["date", "tool_name", "work_hours"]],
                             use_container_width=True, hide_index=True)

    # ── 5. הכנסות לא מסווגות ──
    sec("הכנסות ללא קטגוריה מפורשת")
    income = df[df["amount"] < 0] if "amount" in df.columns else df.iloc[0:0]
    unclassified_income = income[income["category"].isin([
        "אחר", "הוצאות תפעוליות", "הוצאות פרויקט", "הוצאות שכר/כלליות"
    ])] if "category" in income.columns else income.iloc[0:0]
    if unclassified_income.empty:
        ins("green", "✓", "כל ההכנסות מסווגות", "")
    else:
        cols = [c for c in ["date", "account_num", "account_name", "supplier",
                            "description", "amount"] if c in unclassified_income.columns]
        display_dataframe(unclassified_income[cols], use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════
    # סיווג ואיכות נתונים (לפי המפרט החדש)
    # ════════════════════════════════════════════════════════
    if "main_category" not in chash.columns:
        ins("amber", "⚠️", "בנה מאסטר מחדש לקבלת בדיקות סיווג",
            "<code>python -c \"from pipeline import build_master; build_master()\"</code>")
        return

    # ── 6. דלק לא מסווג ──
    sec("דלק לא מסווג", meta="תיאור כולל 'דלק' בלי פירוט סולר/בנזין/חשמל")
    unc_fuel = chash[chash["sub_category"] == "דלק לא מסווג"]
    if unc_fuel.empty:
        ins("green", "✓", "כל הדלק מסווג", "אין תנועות דלק עמומות.")
    else:
        st.caption(f"{len(unc_fuel)} תנועות. בדוק את התיאור והוסף keywords אם חסר.")
        cols = [c for c in ["date", "account_num", "supplier", "description",
                            "net_amount", "classification_note"] if c in unc_fuel.columns]
        heb = {"date": "תאריך", "account_num": "חשבון", "supplier": "ספק",
               "description": "פרטים", "net_amount": "סכום (₪)",
               "classification_note": "הסבר"}
        disp = unc_fuel[cols].copy()
        if "net_amount" in disp.columns:
            disp["net_amount"] = disp["net_amount"].round(0)
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── 7. זיכויים בהוצאות (לוודא שלא נספרו כהכנסה) ──
    sec("זיכויים בהוצאות", meta="זכות בכרטיס הוצאה = הקטנת הוצאה, לא הכנסה")
    exp_credits = chash[(chash["account_type"] == "expense") & (chash["is_credit_note"] == True)]
    if exp_credits.empty:
        ins("green", "✓", "אין זיכויים בהוצאות", "")
    else:
        st.caption(f"{len(exp_credits)} זיכויים - הם הקטינו את ההוצאה הרלוונטית (לא נספרו כהכנסה).")
        cols = [c for c in ["date", "account_num", "account_name", "supplier",
                            "description", "credit", "net_amount", "sub_category"]
                if c in exp_credits.columns]
        heb = {"date": "תאריך", "account_num": "חשבון", "account_name": "שם חשבון",
               "supplier": "ספק", "description": "פרטים", "credit": "זכות",
               "net_amount": "נטו (₪)", "sub_category": "תת-קטגוריה"}
        disp = exp_credits[cols].copy()
        for c in ("credit", "net_amount"):
            if c in disp.columns:
                disp[c] = disp[c].round(0)
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── 8. זיכויים בהכנסות (חובה בכרטיס הכנסות = הקטנת הכנסה) ──
    sec("זיכויים/תיקונים בהכנסות", meta="חובה בכרטיס הכנסות = הקטנת הכנסה, לא הוצאה")
    inc_credits = chash[(chash["account_type"] == "revenue") & (chash["is_credit_note"] == True)]
    if inc_credits.empty:
        ins("green", "✓", "אין זיכויים בהכנסות", "")
    else:
        st.caption(f"{len(inc_credits)} זיכויים - הם הקטינו את ההכנסה הרלוונטית (לא נספרו כהוצאה).")
        cols = [c for c in ["date", "account_num", "account_name",
                            "description", "debit", "net_amount"]
                if c in inc_credits.columns]
        heb = {"date": "תאריך", "account_num": "חשבון", "account_name": "שם חשבון",
               "description": "פרטים", "debit": "חובה", "net_amount": "נטו (₪)"}
        disp = inc_credits[cols].copy()
        for c in ("debit", "net_amount"):
            if c in disp.columns:
                disp[c] = disp[c].round(0)
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── 9. חשבונות הכנסה שזוהו ──
    sec("חשבונות הכנסה שזוהו")
    rev_accounts = chash[chash["account_type"] == "revenue"].groupby(
        ["account_num", "account_name"]
    ).agg(
        n_tx=("amount", "size"),
        net_total=("net_amount", "sum"),
    ).reset_index().round(0)
    if rev_accounts.empty:
        ins("amber", "⚠️", "לא זוהו חשבונות הכנסה",
            "ודא שהכרטיס כולל חשבונות עם 'הכנסות' בשם או מספרי 927/951/7367.")
    else:
        rev_accounts.columns = ["מס' חשבון", "שם חשבון", "מס' תנועות", "נטו (₪)"]
        display_dataframe(rev_accounts.sort_values("נטו (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

    # ── 10. חשבונות דלק ואנרגיה - פירוט ──
    sec("פילוח דלק ואנרגיה לפי תת-קטגוריה")
    fuel_rows = chash[chash["main_category"] == "דלק ואנרגיה"]
    if fuel_rows.empty:
        st.caption("אין תנועות בקטגוריית 'דלק ואנרגיה'.")
    else:
        fuel_agg = fuel_rows.groupby("sub_category").agg(
            n_tx=("amount", "size"),
            net_total=("net_amount", "sum"),
            n_suppliers=("supplier", lambda s: s[s != ""].nunique()),
        ).reset_index().round(0)
        fuel_agg.columns = ["תת-קטגוריה", "תנועות", "סכום נטו (₪)", "ספקים"]
        display_dataframe(fuel_agg.sort_values("סכום נטו (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════
    # בדיקות ספקים (לפי הספק החדש בטאב כספים)
    # ════════════════════════════════════════════════════════
    expenses = chash[chash["account_type"] == "expense"] if "account_type" in chash.columns \
        else chash[chash["amount"] > 0]

    # ── 11. ספק לא מזוהה ──
    sec("ספק לא מזוהה - תנועות הוצאה בלי שם ספק")
    from core.chashbashevet_loader import SALARY_ACCOUNTS
    no_sup = expenses[
        (expenses["supplier"].fillna("").astype(str).str.strip() == "") &
        (~expenses["account_num"].isin(SALARY_ACCOUNTS))  # שכר עם supplier ריק זה תקין
    ]
    if no_sup.empty:
        ins("green", "✓", "אין הוצאות חסרות ספק", "")
    else:
        st.caption(f"{len(no_sup)} תנועות הוצאה ללא ספק (לא שכר). סה\"כ ₪{no_sup['net_amount'].sum():,.0f}.")
        cols = [c for c in ["date", "account_num", "account_name",
                            "description", "net_amount"] if c in no_sup.columns]
        display_dataframe(no_sup[cols], use_container_width=True, hide_index=True)

    # ── 12. שכר שזוהה בטעות כספק ──
    sec("שכר שזוהה בטעות כספק", meta="ספק שמכיל 'שכ\"ע' או דפוס תאריך פנימי")
    import re as _re
    bad_sal = expenses[
        expenses["supplier"].fillna("").astype(str).str.match(r"^שכ[\"']?ע?\s*\d", na=False)
    ]
    if bad_sal.empty:
        ins("green", "✓", "אין שכר שזוהה כספק", "")
    else:
        st.caption(f"{len(bad_sal)} תנועות שכר מזוהות בטעות כספק.")
        cols = [c for c in ["date", "account_num", "supplier", "description",
                            "net_amount"] if c in bad_sal.columns]
        display_dataframe(bad_sal[cols], use_container_width=True, hide_index=True)

    # ── 13. ספק שמופיע בכמה קטגוריות ──
    sec("ספק שמופיע ביותר מקטגוריה אחת")
    if not expenses.empty and "main_category" in expenses.columns:
        valid_sup = expenses[expenses["supplier"].fillna("") != ""]
        multi_cat = valid_sup.groupby("supplier")["main_category"].nunique().reset_index()
        multi_cat = multi_cat[multi_cat["main_category"] > 1].rename(
            columns={"main_category": "n_categories"}
        )
        if multi_cat.empty:
            ins("green", "✓", "כל ספק שייך לקטגוריה אחת בלבד", "")
        else:
            # join with category list per supplier
            cats_per = valid_sup.groupby("supplier")["main_category"].apply(
                lambda s: ", ".join(sorted(s.unique()))
            ).reset_index().rename(columns={"main_category": "categories"})
            joined = multi_cat.merge(cats_per, on="supplier")
            joined.columns = ["ספק", "מס' קטגוריות", "קטגוריות"]
            st.caption(f"{len(joined)} ספקים מופיעים ביותר מקטגוריה אחת - לבדוק אם זה נכון.")
            display_dataframe(joined.sort_values("מס' קטגוריות", ascending=False),
                         use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════
    # בדיקות חיבור דלק-לכלי (Step 3 — 9 חריגות חדשות)
    # ════════════════════════════════════════════════════════
    from core.equipment_matcher import enrich_fuel_transactions
    from pipeline import _load_tools_registry, load_fuel_invoices_data
    eq_full = _load_tools_registry()

    # נאסוף את כל מקורות הדלק (כמו ב-_subtab_fuel_purchases)
    all_fuel_qa = []
    solar_qa = df[df["source"] == "solar"] if "source" in df.columns else pd.DataFrame()
    if not solar_qa.empty:
        s = solar_qa.copy()
        s["fuel_type"] = "סולר"
        s["source_kind"] = "solar.xlsx"
        s["total_cost"] = s.get("amount", 0)
        s = s.rename(columns={"liters": "qty_liters"})
        all_fuel_qa.append(s)
    inv_qa = load_fuel_invoices_data(project_meta["project_id"])
    if not inv_qa.empty:
        i = inv_qa.copy()
        i["fuel_type"] = "סולר"
        i["source_kind"] = "fuel_invoices"
        i = i.rename(columns={"item_description": "description", "liters": "qty_liters"})
        all_fuel_qa.append(i)
    if "main_category" in chash.columns:
        cf = chash[chash["main_category"] == "דלק ואנרגיה"]
        if not cf.empty:
            sub_to_type = {
                "סולר צמ\"ה": "סולר", "סולר רכבים": "סולר",
                "בנזין רכבים": "בנזין", "טעינת חשמל רכבים": "חשמל",
                "דלק לא מסווג": "לא מסווג",
            }
            c = cf.copy()
            c["fuel_type"] = c["sub_category"].map(sub_to_type).fillna("לא מסווג")
            c["source_kind"] = "chashbashevet"
            c["qty_liters"] = None
            c["total_cost"] = c.get("net_amount", c.get("amount", 0))
            all_fuel_qa.append(c)

    if all_fuel_qa and not eq_full.empty:
        combined_qa = pd.concat(all_fuel_qa, ignore_index=True, sort=False)
        for col in ("description", "license_num", "tool_name", "qty_liters", "total_cost"):
            if col not in combined_qa.columns:
                combined_qa[col] = None
        enr = enrich_fuel_transactions(combined_qa, eq_full)

        # ── 15. fuel_usage_without_equipment ──
        sec("דלק ללא כלי מזוהה")
        no_eq = enr[enr["matched_by"] == "unmatched"]
        if no_eq.empty:
            ins("green", "✓", "כל הדלק שויך לכלי", "")
        else:
            st.caption(f"{len(no_eq)} תנועות דלק ללא כלי. "
                       f"₪{pd.to_numeric(no_eq['total_cost'], errors='coerce').fillna(0).sum():,.0f}")
            cols = [c for c in ["date", "source_kind", "supplier", "description",
                                  "fuel_type", "qty_liters", "total_cost", "match_note"]
                    if c in no_eq.columns]
            display_dataframe(no_eq[cols].head(50), use_container_width=True, hide_index=True)
            if len(no_eq) > 50:
                st.caption(f"מציג 50 מתוך {len(no_eq)}. כל החריגות ניתנות לייצוא בטאב סולר.")

        # ── 16. fuel_type_mismatch + electric/diesel violations ──
        sec("אי-התאמה בין סוג דלק לסוג כלי")
        mismatch = enr[enr["validation_status"] == "error"]
        if mismatch.empty:
            ins("green", "✓", "אין אי-התאמות", "")
        else:
            cols = [c for c in ["date", "matched_tool_name", "matched_license_num",
                                  "fuel_type", "validation_note", "total_cost"]
                    if c in mismatch.columns]
            display_dataframe(mismatch[cols], use_container_width=True, hide_index=True)

        # ── 17. inactive_equipment_has_fuel ──
        sec("דלק לכלי לא פעיל")
        inactive_alerts = enr[enr["validation_note"].astype(str).str.contains("לא פעיל", na=False)]
        if inactive_alerts.empty:
            ins("green", "✓", "כל הדלק לכלים פעילים", "")
        else:
            st.caption(f"{len(inactive_alerts)} תנועות דלק לכלים מושבתים.")
            cols = [c for c in ["date", "matched_tool_name", "matched_license_num",
                                  "fuel_type", "total_cost"] if c in inactive_alerts.columns]
            display_dataframe(inactive_alerts[cols], use_container_width=True, hide_index=True)

        # ── 17b. תדלוק ללא ליטרים ──
        sec("תדלוק ללא ליטרים")
        no_liters = enr[
            pd.to_numeric(enr["qty_liters"], errors="coerce").isna() &
            (enr["source_kind"] != "chashbashevet")  # chashbashevet לא נושא ליטרים
        ]
        if no_liters.empty:
            ins("green", "✓", "כל התדלוקים כוללים ליטרים", "")
        else:
            cols = [c for c in ["date", "source_kind", "supplier",
                                  "description", "total_cost"] if c in no_liters.columns]
            display_dataframe(no_liters[cols].head(50),
                         use_container_width=True, hide_index=True)
            if len(no_liters) > 50:
                st.caption(f"מציג 50 מתוך {len(no_liters)}.")

        # ── 17c. תדלוק ללא project_id ──
        sec("תדלוק ללא שיוך לפרויקט")
        # בפועל - כל הדאטה כאן כבר מסונן לפרויקט, אבל בודקים שמופיע
        if "project_id" in enr.columns:
            no_proj = enr[enr["project_id"].fillna("").astype(str) == ""]
            if no_proj.empty:
                ins("green", "✓", "כל התדלוקים משויכים לפרויקט", "")
            else:
                cols = [c for c in ["date", "source_kind", "supplier",
                                      "description", "total_cost"] if c in no_proj.columns]
                display_dataframe(no_proj[cols], use_container_width=True, hide_index=True)
        else:
            st.caption("אין עמודת project_id לבדוק.")

        # ── 18. סטטיסטיקת matching וסיווג ──
        sec("סטטיסטיקת חיבור דלק→כלים")
        stats = {
            "סה\"כ תנועות דלק": len(enr),
            "התאמה: license_num": int((enr["matched_by"] == "license_num").sum()),
            "התאמה: license מהפרטים": int((enr["matched_by"] == "license_in_description").sum()),
            "התאמה: שם כלי": int((enr["matched_by"] == "tool_name").sum()),
            "התאמה: חלקי": int((enr["matched_by"] == "partial_tool_name").sum()),
            "לא מותאם": int((enr["matched_by"] == "unmatched").sum()),
        }
        display_dataframe(pd.DataFrame([{"מקור התאמה": k, "כמות": v} for k, v in stats.items()]),
                     use_container_width=True, hide_index=True)

    # ── 19. סטטיסטיקת מקור סיווג דלק: מקובץ כללים מול ברירת מחדל ──
    sec("מקור סיווג דלק: קובץ כללים מול ברירת מחדל")
    fuel_rows_all = chash[chash["main_category"] == "דלק ואנרגיה"] \
        if "main_category" in chash.columns else pd.DataFrame()
    if fuel_rows_all.empty:
        st.caption("אין תנועות דלק.")
    else:
        note_col = fuel_rows_all["classification_note"].astype(str)
        excel_count = int(note_col.str.contains("fuel_rules.xlsx").sum())
        fallback_count = int(note_col.str.contains("fallback").sum())
        manual_count = int(note_col.str.startswith("חשבון 74327").sum())
        unknown_count = len(fuel_rows_all) - excel_count - fallback_count - manual_count
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("מקובץ כללי דלק", str(excel_count))
        c2.metric("מברירת מחדל", str(fallback_count))
        c3.metric("ישן", str(manual_count))
        c4.metric("אחר/לא ידוע", str(unknown_count))
        if fallback_count > 0:
            ins("amber", "⚠️", f"{fallback_count} תנועות סווגו ע\"י כלל ברירת מחדל",
                "מומלץ להוסיף כללים מתאימים לקובץ כללי הדלק")

    # ── 14. ספקים עם סכומים חריגים ──
    sec("ספקים עם סכומים חריגים", meta="חריגות סטטיסטיות")
    if not expenses.empty:
        sup_sums = expenses[expenses["supplier"].fillna("") != ""].groupby(
            "supplier")["net_amount"].sum()
        if len(sup_sums) >= 3:
            med = sup_sums.median()
            std = sup_sums.std()
            if std and std > 0:
                z = (sup_sums - med) / std
                outliers = sup_sums[z.abs() > 3]
                if outliers.empty:
                    ins("green", "✓", "אין ספקים חריגים סטטיסטית", "")
                else:
                    rows = pd.DataFrame({
                        "ספק": outliers.index,
                        "סכום (₪)": outliers.values.round(0),
                        "מעל החציון ב-": ((outliers / med - 1) * 100).round(0).values,
                    })
                    st.caption(f"{len(outliers)} ספקים חריגים (החציון: ₪{med:,.0f}).")
                    display_dataframe(rows, use_container_width=True, hide_index=True)

    # ── היסטוריית audit ──
    st.markdown("---")
    sec("📜 היסטוריית פעולות (Audit Log)",
        meta="50 הפעולות האחרונות במערכת")
    try:
        from core import db
        recent = db.recent_events(50)
        if recent.empty:
            st.caption("אין רישומי audit עדיין.")
        else:
            # סינון לפעולות שקשורות לפרויקט הנוכחי
            mask = recent["details"].astype(str).str.contains(
                project_id, na=False,
            )
            project_only = recent[mask]
            view_choice = st.radio(
                "תצוגה", ["רק הפרויקט הנוכחי", "כל המערכת"],
                horizontal=True, key=f"audit_view_{project_id}",
            )
            audit_to_show = project_only if view_choice == "רק הפרויקט הנוכחי" else recent
            if audit_to_show.empty:
                st.caption("אין רישומים לפרויקט זה.")
            else:
                disp = audit_to_show[["timestamp", "event", "details"]].copy()
                disp.columns = ["תאריך", "פעולה", "פרטים"]
                display_dataframe(disp.head(50))
    except Exception as e:
        st.caption(f"audit log לא זמין: {e}")


# ════════════════════════════════════════════════════════════
# Helper: ייצוא DataFrame לאקסל בלי כפילויות קוד
# ════════════════════════════════════════════════════════════
def _excel_download(df: pd.DataFrame, sheet_name: str, file_name: str,
                      label: str | None = None, key: str | None = None) -> None:
    """כפתור הורדה אחיד ל-DataFrame כאקסל."""
    if df.empty:
        return
    from io import BytesIO
    buf = BytesIO()
    safe_sheet = "".join(c if c.isalnum() else "_" for c in sheet_name)[:31]
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=safe_sheet, index=False)
    btn_label = label or f"⬇️ הורד {len(df):,} שורות לאקסל"
    st.download_button(
        btn_label, data=buf.getvalue(), file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )


def _heb_columns(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """משנה שמות עמודות לעברית לפי mapping. עמודות לא ב-mapping נשארות."""
    out = df.copy()
    out.columns = [mapping.get(c, c) for c in out.columns]
    return out


_FULL_TX_COL_HEB = {
    "date": "תאריך", "month": "חודש", "account_num": "מס' חשבון",
    "account_name": "שם חשבון", "supplier": "ספק", "description": "פרטים",
    "debit": "חובה", "credit": "זכות", "amount": "סכום",
    "net_amount": "נטו (₪)", "category": "קטגוריה", "subcategory": "תת-קטגוריה",
    "main_category": "קטגוריה ראשית", "sub_category": "תת-קטגוריה",
    "source": "מקור קובץ", "anomaly_flags": "דגלים",
    "classification_confidence": "בטחון סיווג",
    "classification_note": "הסבר סיווג",
    "is_credit_note": "זיכוי",
    "license_num": "מס' רישוי", "tool_name": "שם כלי",
    "liters": "ליטרים", "engine_hours": "שעות מנוע",
    "work_hours": "שעות עבודה",
}


def _render_tx_detail(tx_df: pd.DataFrame, title: str, key_prefix: str,
                       file_basename: str = "transactions") -> None:
    """תצוגת פירוט תנועות אחידה: KPIs + טבלה עם עברית + ייצוא."""
    if tx_df.empty:
        st.caption(f"אין תנועות עבור {title}.")
        return
    n = len(tx_df)
    sum_net = float(tx_df.get("net_amount", tx_df.get("amount", pd.Series([0]))).sum())
    sum_debit = float(tx_df["debit"].sum()) if "debit" in tx_df.columns else 0
    sum_credit = float(tx_df["credit"].sum()) if "credit" in tx_df.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("תנועות", format_number(n))
    c2.metric("נטו", format_currency(sum_net))
    c3.metric("חובה", format_currency(sum_debit))
    c4.metric("זכות", format_currency(sum_credit))

    show_cols = [c for c in [
        "date", "month", "account_num", "account_name", "supplier", "description",
        "debit", "credit", "net_amount", "main_category", "sub_category",
        "classification_confidence", "classification_note", "source",
    ] if c in tx_df.columns]
    disp = tx_df[show_cols].copy()
    if "date" in disp.columns:
        disp = disp.sort_values("date")
    for c in ("debit", "credit", "net_amount", "amount"):
        if c in disp.columns:
            disp[c] = pd.to_numeric(disp[c], errors="coerce").round(0)
    disp = _heb_columns(disp, _FULL_TX_COL_HEB)
    display_dataframe(disp, use_container_width=True, hide_index=True,
                  column_config=build_column_config(disp.columns))
    _excel_download(disp, sheet_name=title[:31],
                     file_name=f"{file_basename}_{key_prefix}.xlsx",
                     key=f"dl_{key_prefix}")


# ════════════════════════════════════════════════════════════
# SUB-TABS חדשים למבנה המקצועי (8 ראשיים)
# ════════════════════════════════════════════════════════════


# ─── כספים → ספקים (פירוט הוצאות לפי ספק) ──────────────────
def _normalize_supplier(supplier: str, account_num: int | None,
                         account_name: str = "") -> str:
    """שיוך supplier לטקסט תצוגה.

    - שכר ללא ספק → "שכר עובדים"
    - ריק/None → "לא זוהה"
    - אחר → השם כפי שהוא.
    """
    from core.chashbashevet_loader import SALARY_ACCOUNTS
    s = (supplier or "").strip()
    if s:
        return s
    if account_num in SALARY_ACCOUNTS:
        return "שכר עובדים"
    return "לא זוהה"


def _supplier_group(sub_cat: str, main_cat: str) -> str:
    """קבוצת ספקים לתצוגה מקובצת."""
    SUPPLIER_GROUPS = {
        "סולר צמ\"ה": "ספקי סולר צמ\"ה",
        "סולר רכבים": "ספקי סולר רכבים",
        "בנזין רכבים": "ספקי בנזין",
        "טעינת חשמל רכבים": "ספקי חשמל רכבים",
        "דלק לא מסווג": "ספקי דלק לא מסווג",
    }
    if sub_cat in SUPPLIER_GROUPS:
        return SUPPLIER_GROUPS[sub_cat]
    if main_cat == "קבלני משנה":
        return "קבלני משנה"
    if main_cat == "אחזקת כלים":
        return "מוסכים / אחזקה"
    if main_cat == "חומרים":
        return "ספקי חומרים"
    if main_cat == "פינוי פסולת":
        return "פינוי פסולת"
    if main_cat == "שכר עבודה":
        return "שכר עובדים"
    return "אחר"


def _subtab_suppliers_finance(df: pd.DataFrame, project_meta: dict) -> None:
    """תת-טאב ספקים בתוך כספים. הוצאות בלבד."""
    # ── סינון בסיסי: רק תנועות הוצאה מחשבשבת ──
    if "source" in df.columns:
        chash = df[df["source"] == "chashbashevet"]
    else:
        chash = df
    if chash.empty:
        ins("blue", "ℹ️", "אין נתוני כרטיס הנהלה", "טען כרטיס הנהלה.")
        return

    # אם יש account_type, השתמש; אחרת fallback ל-amount > 0
    if "account_type" in chash.columns:
        exp = chash[chash["account_type"] == "expense"].copy()
    else:
        exp = chash[chash["amount"] > 0].copy()
    if exp.empty:
        ins("blue", "ℹ️", "אין תנועות הוצאה", "")
        return

    # נרמול ספקים: שכר → "שכר עובדים", ריק → "לא זוהה"
    exp["supplier_display"] = exp.apply(
        lambda r: _normalize_supplier(
            r.get("supplier"), r.get("account_num"), r.get("account_name", "")
        ),
        axis=1,
    )
    # net_amount fallback
    if "net_amount" not in exp.columns:
        exp["net_amount"] = exp["debit"] - exp["credit"] if "debit" in exp.columns else exp["amount"]
    # main_category / sub_category fallback
    if "main_category" not in exp.columns:
        exp["main_category"] = exp.get("category", "")
    if "sub_category" not in exp.columns:
        exp["sub_category"] = exp.get("subcategory", "")

    total_exp = float(exp["net_amount"].sum())

    # ── פילטרים ──
    sec("פילטרים")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        months = ["כל החודשים"] + sorted(exp["month"].dropna().unique().tolist())
        month_pick = st.selectbox("חודש", months, key=f"sup_month_{project_meta['project_id']}")
    with f2:
        cats = ["כל הקטגוריות"] + sorted(exp["main_category"].dropna().unique().tolist())
        cat_pick = st.selectbox("קטגוריה", cats, key=f"sup_cat_{project_meta['project_id']}")
    with f3:
        if cat_pick == "כל הקטגוריות":
            sub_options = sorted(exp["sub_category"].dropna().unique().tolist())
        else:
            sub_options = sorted(exp[exp["main_category"] == cat_pick]
                                  ["sub_category"].dropna().unique().tolist())
        sub_pick = st.selectbox("תת-קטגוריה", ["הכל"] + sub_options,
                                 key=f"sup_sub_{project_meta['project_id']}")
    with f4:
        search = st.text_input("חיפוש ספק / פרטים",
                                key=f"sup_search_{project_meta['project_id']}",
                                placeholder="🔍").strip()

    f5, f6 = st.columns(2)
    with f5:
        min_amt = st.number_input("סכום מינימום (₪)", min_value=0.0, step=1000.0,
                                    value=0.0, key=f"sup_min_{project_meta['project_id']}")
    with f6:
        max_amt = st.number_input("סכום מקסימום (₪, 0 = ללא הגבלה)", min_value=0.0,
                                    step=10000.0, value=0.0,
                                    key=f"sup_max_{project_meta['project_id']}")

    # Apply filters
    filtered = exp.copy()
    if month_pick != "כל החודשים":
        filtered = filtered[filtered["month"] == month_pick]
    if cat_pick != "כל הקטגוריות":
        filtered = filtered[filtered["main_category"] == cat_pick]
    if sub_pick != "הכל":
        filtered = filtered[filtered["sub_category"] == sub_pick]
    if search:
        sl = search.lower()
        mask = (filtered["supplier_display"].astype(str).str.lower().str.contains(sl, na=False) |
                filtered["description"].astype(str).str.lower().str.contains(sl, na=False))
        filtered = filtered[mask]

    if filtered.empty:
        st.caption("אין תנועות תואמות לפילטרים.")
        return

    # ── אגרגציה לפי ספק ──
    agg = filtered.groupby("supplier_display").agg(
        sum_debit=("debit", "sum") if "debit" in filtered.columns else ("net_amount", "sum"),
        sum_credit=("credit", "sum") if "credit" in filtered.columns else ("net_amount", lambda s: 0),
        net=("net_amount", "sum"),
        n_tx=("net_amount", "size"),
        n_months=("month", lambda s: s.nunique()),
        main_cat=("main_category", lambda s: s.mode().iloc[0] if not s.mode().empty else ""),
        sub_cat=("sub_category", lambda s: s.mode().iloc[0] if not s.mode().empty else ""),
    ).reset_index()

    # סכום מינימום/מקסימום
    if min_amt > 0:
        agg = agg[agg["net"].abs() >= min_amt]
    if max_amt > 0:
        agg = agg[agg["net"].abs() <= max_amt]
    if agg.empty:
        st.caption("אין ספקים שעוברים את סף הסכום.")
        return

    agg["pct_total"] = (agg["net"] / total_exp * 100).round(1)
    for c in ("sum_debit", "sum_credit", "net"):
        agg[c] = agg[c].round(0)
    agg = agg.sort_values("net", ascending=False).reset_index(drop=True)

    # ── KPI Cards ──
    sec("סיכום ספקים")
    most_expensive = agg.iloc[0]["supplier_display"] if not agg.empty else "—"
    biggest_cat = agg.groupby("main_cat")["net"].sum().idxmax() if not agg.empty else "—"
    total_credits = float(filtered["credit"].sum()) if "credit" in filtered.columns else 0
    n_unidentified = int((agg["supplier_display"] == "לא זוהה").sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("סה\"כ ספקים", str(len(agg)))
    k2.metric("הוצאות ספקים", format_currency(agg['net'].sum()))
    k3.metric("ספק הכי יקר", str(most_expensive)[:18],
              help=f"₪{agg.iloc[0]['net']:,.0f}" if not agg.empty else "")
    k4.metric("קטגוריה הכי גדולה", str(biggest_cat))
    k5.metric("סה\"כ זיכויים", f"₪{total_credits:,.0f}")

    if n_unidentified:
        ins("amber", "⚠️", f"{n_unidentified} ספקים 'לא זוהה'",
            "תנועות הוצאה ללא שם ספק - בדוק בטאב QA → 'ספק לא מזוהה'.")

    # ── Top 10 ספקים (טבלה) ──
    sec("10 ספקים מובילים", meta="לפי הוצאה נטו")
    top10 = agg.head(10)[["supplier_display", "main_cat", "net", "pct_total", "n_tx"]].copy()
    top10.columns = ["ספק", "קטגוריה ראשית", "סה\"כ נטו (₪)", "% מסך", "תנועות"]
    display_dataframe(top10, use_container_width=True, hide_index=True)

    # ── 🔍 פירוט ספק ──
    sup_options = agg["supplier_display"].dropna().tolist()
    if sup_options:
        from ui.pages.detail_view import drill_launcher
        drill_launcher("supplier", sup_options,
                        label="פתח פירוט ספק", key_suffix="finance_suppliers")

    # ── טבלת ספקים מלאה ──
    sec(f"כל הספקים ({len(agg)})")
    full = agg.copy()
    full.columns = ["ספק", "סה\"כ חובה", "סה\"כ זכות", "הוצאה נטו",
                    "תנועות", "חודשים", "קטגוריה ראשית", "תת-קטגוריה", "% מסך"]
    display_dataframe(full, use_container_width=True, hide_index=True)

    # ── הפרדה לפי סוג ספק ──
    sec("הפרדה לפי סוג ספק")
    filtered["supplier_group"] = filtered.apply(
        lambda r: _supplier_group(r.get("sub_category", ""), r.get("main_category", "")),
        axis=1,
    )
    by_grp = filtered.groupby("supplier_group").agg(
        net=("net_amount", "sum"),
        n_sup=("supplier_display", "nunique"),
        n_tx=("net_amount", "size"),
    ).reset_index().round(0).sort_values("net", ascending=False)
    by_grp.columns = ["קבוצת ספקים", "סה\"כ (₪)", "ספקים", "תנועות"]
    display_dataframe(by_grp, use_container_width=True, hide_index=True)

    # ── Drill-down: בחירת ספק לפירוט מלא ──
    sec("פירוט תנועות לספק", meta="בחר ספק לפירוט מלא + ייצוא לאקסל")
    sup_pick = st.selectbox(
        "בחר ספק", ["— בחר —"] + agg["supplier_display"].tolist(),
        key=f"sup_drill_{project_meta['project_id']}",
    )
    if sup_pick and sup_pick != "— בחר —":
        sup_tx = filtered[filtered["supplier_display"] == sup_pick].copy()
        sum_debit = float(sup_tx["debit"].sum()) if "debit" in sup_tx.columns else 0
        sum_credit = float(sup_tx["credit"].sum()) if "credit" in sup_tx.columns else 0
        sum_net = float(sup_tx["net_amount"].sum())
        n_months = int(sup_tx["month"].nunique())
        cA, cB, cC, cD = st.columns(4)
        cA.metric("חובה", format_currency(sum_debit))
        cB.metric("זכות (זיכויים)", format_currency(sum_credit))
        cC.metric("נטו", format_currency(sum_net))
        cD.metric("חודשים פעילים", str(n_months))

        # טבלת פירוט
        detail_cols = [c for c in [
            "date", "month", "account_num", "account_name", "description",
            "debit", "credit", "net_amount", "main_category", "sub_category",
            "classification_confidence", "classification_note", "source",
        ] if c in sup_tx.columns]
        heb = {
            "date": "תאריך", "month": "חודש", "account_num": "מס' חשבון",
            "account_name": "שם חשבון", "description": "פרטים",
            "debit": "חובה", "credit": "זכות", "net_amount": "הוצאה נטו",
            "main_category": "קטגוריה ראשית", "sub_category": "תת-קטגוריה",
            "classification_confidence": "בטחון", "classification_note": "הסבר",
            "source": "מקור קובץ",
        }
        disp = sup_tx[detail_cols].copy().sort_values(
            "date" if "date" in detail_cols else detail_cols[0])
        for c in ("debit", "credit", "net_amount"):
            if c in disp.columns:
                disp[c] = disp[c].round(0)
        disp.columns = [heb.get(c, c) for c in detail_cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

        # ייצוא אקסל
        from io import BytesIO
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            disp.to_excel(writer, sheet_name=str(sup_pick)[:31], index=False)
        st.download_button(
            f"⬇️ ייצוא {len(disp)} תנועות של '{sup_pick}' לאקסל",
            data=buf.getvalue(),
            file_name=f"supplier_{sup_pick[:30]}_{project_meta['project_id']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ─── תפעול ושטח → שעות עבודה כלים ───────────────────────────
def _drill_hours_by_entity(combined: pd.DataFrame, entity_col: str,
                             entity_label: str, key_prefix: str,
                             month_col: str = "month_label") -> None:
    """Drill-down כללי לטאב שעות: בחר ישות (כלי/עובד/קבלן/חודש) → פירוט."""
    if combined.empty:
        return
    sec(f"🔍 פירוט לפי {entity_label}")
    dim = st.radio(f"ממד לפירוט", [entity_label, "חודש"],
                     horizontal=True, key=f"{key_prefix}_dim")
    if dim == entity_label:
        if entity_col not in combined.columns:
            st.caption("אין נתונים.")
            return
        opts = sorted([str(x) for x in combined[entity_col].dropna().unique()
                        if str(x).strip()])
        pick = st.selectbox(f"בחר {entity_label}", ["— בחר —"] + opts,
                              key=f"{key_prefix}_pick")
        if pick != "— בחר —":
            sub = combined[combined[entity_col].astype(str) == pick]
            _render_hours_detail(sub, title=pick, key_prefix=f"{key_prefix}_{pick[:20]}")
    else:
        mcol = month_col if month_col in combined.columns else \
                ("month" if "month" in combined.columns else None)
        if mcol is None:
            st.caption("אין עמודת חודש.")
            return
        months = sorted([str(x) for x in combined[mcol].dropna().unique()])
        pick = st.selectbox("בחר חודש", ["— בחר —"] + months,
                              key=f"{key_prefix}_month_pick")
        if pick != "— בחר —":
            sub = combined[combined[mcol].astype(str) == pick]
            _render_hours_detail(sub, title=pick, key_prefix=f"{key_prefix}_m_{pick}")


def _render_hours_detail(df: pd.DataFrame, title: str, key_prefix: str) -> None:
    """תצוגת פירוט שעות עבודה אחידה."""
    if df.empty:
        st.caption(f"אין רשומות עבור {title}.")
        return
    total_h = 0
    if "work_hours" in df.columns:
        total_h = float(pd.to_numeric(df["work_hours"], errors="coerce").fillna(0).sum())
    elif "hours" in df.columns:
        total_h = float(pd.to_numeric(df["hours"], errors="coerce").fillna(0).sum())
    days = 0
    if "date" in df.columns:
        days = int(pd.to_datetime(df["date"], errors="coerce").dropna().nunique())

    c1, c2, c3 = st.columns(3)
    c1.metric("רשומות", str(len(df)))
    c2.metric("סה\"כ שעות", f"{total_h:,.1f}")
    c3.metric("ימים", str(days))

    cols = [c for c in ["date", "name", "tool_name", "license_num", "operator",
                          "start_time", "end_time", "work_hours", "hours", "days",
                          "engine_hours", "section", "notes", "project_id"]
            if c in df.columns]
    heb = {"date": "תאריך", "name": "שם", "tool_name": "כלי", "license_num": "רישוי",
            "operator": "מפעיל", "start_time": "התחלה", "end_time": "סיום",
            "work_hours": "ש\"ע", "hours": "שעות", "days": "ימים",
            "engine_hours": "ש\"מ", "section": "סעיף", "notes": "הערות",
            "project_id": "פרויקט"}
    disp = df[cols].copy()
    if "date" in disp.columns:
        disp = disp.sort_values("date")
    disp.columns = [heb.get(c, c) for c in cols]
    display_dataframe(disp, use_container_width=True, hide_index=True)
    _excel_download(disp, sheet_name=title[:31],
                      file_name=f"hours_{key_prefix}.xlsx",
                      key=f"dl_hours_{key_prefix}")


def _subtab_equipment_hours(df: pd.DataFrame, project_meta: dict) -> None:
    """שעות עבודה כלים - מאחד hours.xlsx + site_tracking + control_db."""
    sec("שעות עבודה כלים", meta="מאוחד מדוח שעות + יומן שטח + הזנה ידנית")
    project_id = project_meta["project_id"]

    hours_master = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    from pipeline import load_site_tracking_data
    site_data = load_site_tracking_data(project_id)
    site_hours = site_data.get("tools_hours", pd.DataFrame())
    from core import control_db
    manual = control_db.list_rows("equipment_work_logs", project_id)

    sources = []
    if not hours_master.empty:
        sources.append(("דוח שעות", len(hours_master), float(hours_master["work_hours"].sum())))
    if not site_hours.empty and "work_hours" in site_hours.columns:
        sources.append(("יומן שטח", len(site_hours), float(site_hours["work_hours"].sum())))
    if not manual.empty and "work_hours" in manual.columns:
        sources.append(("הזנה ידנית", len(manual), float(manual["work_hours"].sum())))

    if not sources:
        ins("blue", "ℹ️", "אין נתוני שעות עבודה כלים",
            "טען דוח שעות עבודה או הוסף שעות בטאב 'יומני שטח'.")
        return

    cols_kpi = st.columns(len(sources) + 1)
    cols_kpi[0].metric("מקורות נתונים", str(len(sources)))
    for i, (src, n, h) in enumerate(sources):
        cols_kpi[i + 1].metric(f"{src}", f"{h:,.0f} ש'", help=f"{n} שורות")

    if not site_hours.empty:
        sec("מיומן שטח")
        cols = [c for c in ["date", "tool_name", "license_num", "start_time",
                            "end_time", "work_hours", "section", "notes"]
                if c in site_hours.columns]
        heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
               "start_time": "התחלה", "end_time": "סיום", "work_hours": "שעות",
               "section": "סעיף", "notes": "הערות"}
        disp = site_hours[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp.head(200), use_container_width=True, hide_index=True)
        if len(site_hours) > 200:
            st.caption(f"מציג 200 מתוך {len(site_hours)}")

    if not manual.empty:
        sec("מהזנה ידנית")
        cols = [c for c in ["date", "tool_name", "license_num", "operator",
                            "work_hours", "engine_hours", "notes"] if c in manual.columns]
        heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
               "operator": "מפעיל", "work_hours": "ש\"ע", "engine_hours": "ש\"מ",
               "notes": "הערות"}
        disp = manual[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── Drill-Down: בחר כלי/חודש ──
    combined = []
    if not site_hours.empty:
        s = site_hours.copy()
        s["source"] = "site_tracking"
        combined.append(s)
    if not manual.empty:
        m = manual.copy()
        m["tool_name"] = m.get("tool_name", "")
        m["source"] = "manual"
        if "operator" in m.columns and "name" not in m.columns:
            m["name"] = m["operator"]
        combined.append(m)
    if combined:
        all_h = pd.concat(combined, ignore_index=True, sort=False)
        _drill_hours_by_entity(all_h, "tool_name", "כלי",
                                 key_prefix="eqh", month_col="month_label")


# ─── תפעול ושטח → קבלני משנה בשטח ──────────────────────────
def _subtab_contractors_field(df: pd.DataFrame, project_meta: dict) -> None:
    """קבלני משנה - שעות בשטח בלבד (החיובים הכספיים בטאב 'ספקים')."""
    project_id = project_meta["project_id"]
    from pipeline import load_site_tracking_data
    site_data = load_site_tracking_data(project_id)
    sub_hours = site_data.get("subcontractors_hours", pd.DataFrame())
    from core import control_db
    manual = control_db.list_rows("contractor_work_logs", project_id)

    sec("קבלני משנה - שעות עבודה בשטח")
    if sub_hours.empty and manual.empty:
        ins("blue", "ℹ️", "אין נתוני קבלני משנה",
            "טען יומן שטח או הוסף שעות בטאב 'יומני שטח'.")
        return

    if not sub_hours.empty:
        per = sub_hours.groupby("name").agg(
            days=("date", "nunique"),
            hours=("work_hours", "sum"),
        ).reset_index().sort_values("hours", ascending=False).round(1)
        per.columns = ["שם קבלן/משאית", "ימי עבודה", "סה\"כ שעות"]
        display_dataframe(per, use_container_width=True, hide_index=True)

        with st.expander("פירוט יומי"):
            cols = [c for c in ["date", "name", "license_num", "start_time",
                                "end_time", "work_hours", "notes"] if c in sub_hours.columns]
            heb = {"date": "תאריך", "name": "שם", "license_num": "מס' רכב",
                   "start_time": "התחלה", "end_time": "סיום",
                   "work_hours": "שעות", "notes": "הערות"}
            disp = sub_hours[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            display_dataframe(disp, use_container_width=True, hide_index=True)

    if not manual.empty:
        sec("הזנות ידניות")
        cols = [c for c in ["date", "contractor_name", "work_type", "quantity",
                            "hours", "days", "price", "invoice_num"] if c in manual.columns]
        heb = {"date": "תאריך", "contractor_name": "שם קבלן", "work_type": "סוג עבודה",
               "quantity": "כמות", "hours": "שעות", "days": "ימים",
               "price": "מחיר", "invoice_num": "חשבונית"}
        disp = manual[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── Drill-Down: בחר קבלן / חודש ──
    combined_c = []
    if not sub_hours.empty:
        s = sub_hours.copy()
        s["source"] = "site_tracking"
        combined_c.append(s)
    if not manual.empty:
        m = manual.copy()
        m["name"] = m.get("contractor_name", "")
        m["source"] = "manual"
        combined_c.append(m)
    if combined_c:
        all_c = pd.concat(combined_c, ignore_index=True, sort=False)
        _drill_hours_by_entity(all_c, "name", "קבלן",
                                 key_prefix="con", month_col="month_label")


# ─── סולר וכלים → קניות סולר ───────────────────────────────
def _subtab_fuel_purchases(df: pd.DataFrame, project_meta: dict) -> None:
    """קניות סולר - הפרדה לפי סוג דלק (סולר צמ"ה/רכבים/בנזין/חשמל) + מקורות שונים."""
    from pipeline import load_fuel_invoices_data
    from core.fuel_invoices_loader import summary_by_supplier, summary_by_month

    # ── ראש: 5 כרטיסים לפי סוג דלק ──
    sec("פילוח דלק ואנרגיה לפי סוג", meta="מבוסס על סוג חשבון + תיאור")
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
    if "main_category" not in chash.columns:
        # parquet ישן - לא מכיל את השדות החדשים
        ins("amber", "⚠️", "צריך לבנות מאסטר מחדש",
            "הרץ <code>python -c \"from pipeline import build_master; build_master()\"</code> "
            "כדי לקבל את הפרדת סוגי הדלק.")
    else:
        fuel = chash[chash["main_category"] == "דלק ואנרגיה"]
        if fuel.empty:
            st.caption("אין תנועות בקטגוריית 'דלק ואנרגיה'.")
        else:
            # 5 כרטיסים
            FUEL_TYPES = ["סולר צמ\"ה", "סולר רכבים", "בנזין רכבים",
                          "טעינת חשמל רכבים", "דלק לא מסווג"]
            ICONS = {"סולר צמ\"ה": "🚜", "סולר רכבים": "🚗",
                     "בנזין רכבים": "⛽", "טעינת חשמל רכבים": "🔌",
                     "דלק לא מסווג": "❓"}
            total_fuel = float(fuel["net_amount"].sum())
            cols = st.columns(5)
            for col, ft in zip(cols, FUEL_TYPES):
                sub = fuel[fuel["sub_category"] == ft]
                amt = float(sub["net_amount"].sum())
                n = len(sub)
                pct = (amt / total_fuel * 100) if total_fuel else 0
                with col:
                    bg = "#FFFBEB" if ft == "דלק לא מסווג" and n > 0 else "#F0FDF4"
                    border = "#FDE68A" if ft == "דלק לא מסווג" and n > 0 else "#BBF7D0"
                    st.markdown(
                        f"""<div style="background:{bg};border:1px solid {border};
                        border-radius:10px;padding:14px 12px;text-align:center">
                          <div style="font-size:22px">{ICONS[ft]}</div>
                          <div style="font-size:11px;font-weight:700;color:#475569;
                            margin:4px 0">{ft}</div>
                          <div style="font-size:18px;font-weight:800;color:#0F172A">
                            ₪{amt:,.0f}</div>
                          <div style="font-size:10px;color:#64748B;margin-top:4px">
                            {n} תנועות · {pct:.1f}%</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

            # פירוט לפי סוג דלק
            for ft in FUEL_TYPES:
                sub = fuel[fuel["sub_category"] == ft]
                if sub.empty:
                    continue
                with st.expander(f"{ICONS[ft]} {ft} · ₪{sub['net_amount'].sum():,.0f} · {len(sub)} תנועות"):
                    # ספקים עיקריים
                    if "supplier" in sub.columns:
                        sup = sub[sub["supplier"] != ""].groupby("supplier")["net_amount"].agg(
                            ["sum", "count"]).reset_index()
                        if not sup.empty:
                            sup.columns = ["ספק", "סה\"כ (₪)", "תנועות"]
                            sup["סה\"כ (₪)"] = sup["סה\"כ (₪)"].round(0)
                            st.markdown("**ספקים עיקריים**")
                            display_dataframe(sup.sort_values("סה\"כ (₪)", ascending=False),
                                         use_container_width=True, hide_index=True)
                    # פירוט תנועות
                    show_cols = [c for c in ["date", "month", "supplier", "description",
                                              "debit", "credit", "net_amount"]
                                  if c in sub.columns]
                    heb = {"date": "תאריך", "month": "חודש", "supplier": "ספק",
                           "description": "פרטים", "debit": "חובה",
                           "credit": "זכות", "net_amount": "סכום נטו"}
                    disp = sub[show_cols].copy().sort_values(
                        "date" if "date" in show_cols else show_cols[0])
                    for c in ("debit", "credit", "net_amount"):
                        if c in disp.columns:
                            disp[c] = disp[c].round(0)
                    disp.columns = [heb.get(c, c) for c in show_cols]
                    st.markdown("**פירוט תנועות**")
                    display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── דלק לפי כלי - שילוב מקורות + matching ל-equipment ──
    sec("דלק לפי כלי", meta="חיבור אוטומטי לרשימת הכלים")
    from core.equipment_matcher import enrich_fuel_transactions
    from pipeline import _load_tools_registry, load_fuel_invoices_data
    equipment = _load_tools_registry()
    if equipment.empty:
        st.caption("אין כלים ברשימת הכלים — לא ניתן להתאים.")
    else:
        # איסוף כל מקורות הדלק (לאיחוד)
        all_fuel = []

        # מקור 1: solar.xlsx (Pointer) - יש license_num ישיר
        solar_rows = df[df["source"] == "solar"] if "source" in df.columns else pd.DataFrame()
        if not solar_rows.empty:
            s = solar_rows.copy()
            s["fuel_type"] = "סולר"  # Pointer הוא סולר בלבד
            s["source_kind"] = "solar.xlsx"
            s = s.rename(columns={"liters": "qty_liters"})
            if "amount" in s.columns:
                s["total_cost"] = s["amount"]
            else:
                s["total_cost"] = 0
            all_fuel.append(s)

        # מקור 2: fuel_invoices.parquet - יש license בתיאור
        inv = load_fuel_invoices_data(project_meta["project_id"])
        if not inv.empty:
            i = inv.copy()
            i["fuel_type"] = "סולר"  # רובם סולר; אפשר לעדן בעתיד
            i["source_kind"] = "fuel_invoices"
            i = i.rename(columns={"item_description": "description",
                                    "liters": "qty_liters"})
            all_fuel.append(i)

        # מקור 3: chashbashevet fuel rows (74317/74327)
        chash_fuel = chash[chash["main_category"] == "דלק ואנרגיה"] \
            if "main_category" in chash.columns else pd.DataFrame()
        if not chash_fuel.empty:
            c = chash_fuel.copy()
            # נסה לזהות fuel_type לפי sub_category
            sub_to_type = {
                "סולר צמ\"ה": "סולר", "סולר רכבים": "סולר",
                "בנזין רכבים": "בנזין", "טעינת חשמל רכבים": "חשמל",
                "דלק לא מסווג": "לא מסווג",
            }
            c["fuel_type"] = c["sub_category"].map(sub_to_type).fillna("לא מסווג")
            c["source_kind"] = "chashbashevet"
            c["qty_liters"] = None  # אין ליטרים בכרטיס
            if "net_amount" in c.columns:
                c["total_cost"] = c["net_amount"]
            else:
                c["total_cost"] = c["amount"]
            all_fuel.append(c)

        if not all_fuel:
            st.caption("אין נתוני דלק בכלל.")
        else:
            combined = pd.concat(all_fuel, ignore_index=True, sort=False)
            # נרמל עמודות חסרות
            for col in ("description", "license_num", "tool_name", "fuel_type",
                          "qty_liters", "total_cost"):
                if col not in combined.columns:
                    combined[col] = None

            # Enrich: equipment_id + matched_by + match_confidence + validation
            enriched = enrich_fuel_transactions(
                combined, equipment,
                license_col="license_num", tool_name_col="tool_name",
                description_col="description", fuel_type_col="fuel_type",
            )

            # ── סטטיסטיקת matching: פילוח 4-קטגוריות ──
            from core.equipment_matcher import (
                CLASS_MATCHED, CLASS_MISSING, CLASS_BULK, CLASS_UNMATCHED,
            )
            n_total = len(enriched)
            n_by_class = enriched["classification"].value_counts().to_dict()
            n_matched = n_by_class.get(CLASS_MATCHED, 0)
            n_missing = n_by_class.get(CLASS_MISSING, 0)
            n_bulk    = n_by_class.get(CLASS_BULK, 0)
            n_unmatched = n_by_class.get(CLASS_UNMATCHED, 0)

            mk1, mk2, mk3, mk4, mk5 = st.columns(5)
            mk1.metric("סה\"כ תנועות דלק", format_number(n_total))
            mk2.metric("✓ הותאם לכלי", format_number(n_matched),
                       delta=f"{(n_matched/n_total*100):.0f}%" if n_total else None)
            mk3.metric("📦 מסירה לצובר", format_number(n_bulk),
                       help="חשבונית מספק דלק לפרויקט שלם — לא רכב ספציפי")
            mk4.metric("⚠ כלי חסר ברשימה", format_number(n_missing),
                       help="מס' רישוי חולץ מהתיאור אך לא נמצא ב-tools_registry")
            mk5.metric("❓ ללא זיהוי", format_number(n_unmatched),
                       help="לא חולץ רישוי, לא ספק צובר מזוהה — דורש בדיקה ידנית")

            # שורת validation מתחת
            n_err = int((enriched["validation_status"] == "error").sum())
            n_warn = int((enriched["validation_status"] == "warning").sum())
            if n_err or n_warn:
                st.caption(
                    f"🔍 validation: {n_warn:,} אזהרות · {n_err:,} שגיאות "
                    "(אי-התאמה בין סוג דלק לסוג כלי). פירוט בהמשך."
                )

            # ── סיכום לפי כלי ──
            matched = enriched[enriched["matched_by"] != "unmatched"].copy()
            if not matched.empty:
                # קישור לכלי המקורי
                eq_lookup = equipment.set_index("license_num", drop=False)
                summary = matched.groupby("matched_license_num").agg(
                    tool_name=("matched_tool_name",
                                  lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
                    n_tx=("matched_by", "size"),
                    total_liters=("qty_liters", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                    total_cost=("total_cost", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                    n_months=("month", lambda s: s.nunique() if "month" in matched.columns else 0),
                    n_errors=("validation_status", lambda s: (s == "error").sum()),
                ).reset_index()
                # הוסף מטא-נתונים מהכלי
                summary["equipment_group"] = summary["matched_license_num"].map(
                    lambda lic: eq_lookup.loc[lic].get("equipment_group", "")
                    if lic in eq_lookup.index else ""
                )
                summary["fuel_type_defined"] = summary["matched_license_num"].map(
                    lambda lic: eq_lookup.loc[lic].get("fuel_type", "")
                    if lic in eq_lookup.index else ""
                )
                summary["status"] = summary["n_errors"].apply(
                    lambda n: "❌ חריגה" if n else "✓ תקין")
                summary["total_liters"] = summary["total_liters"].round(0)
                summary["total_cost"] = summary["total_cost"].round(0)

                disp = summary[["matched_license_num", "tool_name", "equipment_group",
                                  "fuel_type_defined", "total_liters", "total_cost",
                                  "n_tx", "n_months", "status"]].copy()
                disp.columns = ["מס' רישוי", "שם כלי", "קבוצה", "סוג דלק מוגדר",
                                "ליטרים", "סה\"כ ₪", "תנועות", "חודשים", "סטטוס"]
                display_dataframe(disp.sort_values("סה\"כ ₪", ascending=False),
                             use_container_width=True, hide_index=True)
            else:
                st.caption("אף תנועת דלק לא הצליחה להתאים לכלי.")

            # ── רכבים שזוהו בתיאור אבל חסרים ב-registry ──
            from core.equipment_matcher import unmatched_vehicle_candidates
            candidates = unmatched_vehicle_candidates(enriched)
            if not candidates.empty:
                sec("רכבים מזוהים בתיאור אבל חסרים ברשימת הכלים",
                    meta="הוסף אותם בטאב 'כלים → רשימת כלים' להתאמה אוטומטית")
                ins("amber", "⚠️", f"זוהו {len(candidates)} רכבים חסרים",
                    "המערכת חילצה את מספרי הרישוי מהפרטים אך לא מצאה אותם ברשימת הכלים. "
                    "הוסף אותם כדי שהדלק יתאים אוטומטית בעתיד.")
                cand_disp = candidates.copy()
                # זיהוי סוג דלק לפי הפרטים הראשון
                def _guess_fuel_type(desc):
                    d = (desc or "").lower()
                    if any(k in d for k in ["טעינת רכב חשמלי", "רכב חשמלי", "אפקון", "תחבורה חשמלית"]):
                        return "חשמל"
                    if "בנזין" in d: return "בנזין"
                    if "סולר" in d: return "סולר"
                    return "לא ידוע"
                cand_disp["סוג דלק משוער"] = cand_disp["sample_description"].apply(_guess_fuel_type)
                cand_disp.columns = ["מס' רישוי שחולץ", "פרטים",
                                       "תנועות", "סה\"כ (₪)", "סוג דלק משוער"]
                display_dataframe(cand_disp, use_container_width=True, hide_index=True)

                # ייצוא הרכבים החסרים לאקסל
                from io import BytesIO
                bbuf = BytesIO()
                with pd.ExcelWriter(bbuf, engine="openpyxl") as writer:
                    cand_disp.to_excel(writer, sheet_name="רכבים חסרים", index=False)
                st.download_button(
                    f"⬇️ ייצוא רשימת {len(candidates)} רכבים חסרים",
                    data=bbuf.getvalue(),
                    file_name=f"missing_vehicles_{project_meta['project_id']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            # ── מסירות לצובר (bulk_delivery) — לא דורשות שיוך לכלי ──
            bulk = enriched[enriched["classification"] == CLASS_BULK]
            if not bulk.empty:
                bulk_total = pd.to_numeric(bulk["total_cost"], errors="coerce").fillna(0).sum()
                sec(f"📦 מסירות סולר לצובר ({len(bulk)} תנועות · ₪{bulk_total:,.0f})",
                    meta="חשבוניות מספקי דלק לפרויקט (לא לרכב ספציפי) — מהוות קניות למלאי")
                ins("blue", "ℹ️",
                    "מסירות אלו לא דורשות שיוך לכלי מסוים.",
                    "הסולר נכנס למיכל הפרויקט/צובר. השימוש בפועל מתועד בנפרד "
                    "בטאב 'שימוש בסולר' (מ-יומן שטח).")
                cols = [c for c in ["date", "month", "supplier", "description",
                                    "total_cost", "fuel_type"]
                        if c in bulk.columns]
                heb_b = {"date": "תאריך", "month": "חודש", "supplier": "ספק",
                         "description": "פרטים", "total_cost": "₪",
                         "fuel_type": "סוג דלק"}
                disp_b = bulk[cols].copy()
                if "total_cost" in disp_b.columns:
                    disp_b["total_cost"] = pd.to_numeric(disp_b["total_cost"], errors="coerce").round(0)
                disp_b.columns = [heb_b.get(c, c) for c in cols]
                display_dataframe(disp_b, use_container_width=True, hide_index=True)

            # ── תנועות ללא זיהוי כלי וללא ספק צובר מזוהה ──
            unmatched_strict = enriched[enriched["classification"] == CLASS_UNMATCHED]
            if not unmatched_strict.empty:
                sec(f"❓ דלק ללא זיהוי ({len(unmatched_strict)} תנועות)",
                    meta="לא חולץ רישוי, לא ספק צובר — דורש בדיקה ידנית")
                cols = [c for c in ["date", "month", "source_kind", "supplier",
                                    "description", "qty_liters", "total_cost",
                                    "fuel_type", "match_note"]
                        if c in unmatched_strict.columns]
                heb = {"date": "תאריך", "month": "חודש", "source_kind": "מקור",
                       "supplier": "ספק", "description": "פרטים",
                       "qty_liters": "ליטרים", "total_cost": "₪", "fuel_type": "סוג דלק",
                       "match_note": "הערת התאמה"}
                disp_u = unmatched_strict[cols].copy()
                for c in ("qty_liters", "total_cost"):
                    if c in disp_u.columns:
                        disp_u[c] = pd.to_numeric(disp_u[c], errors="coerce").round(0)
                disp_u.columns = [heb.get(c, c) for c in cols]
                display_dataframe(disp_u, use_container_width=True, hide_index=True)

                # ייצוא חריגות
                from io import BytesIO
                buf = BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    disp_u.to_excel(writer, sheet_name="ללא זיהוי", index=False)
                st.download_button(
                    f"⬇️ ייצוא {len(unmatched_strict)} תנועות ללא זיהוי לאקסל",
                    data=buf.getvalue(),
                    file_name=f"fuel_unmatched_{project_meta['project_id']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            # ── חריגות validation ──
            errors = enriched[enriched["validation_status"] == "error"]
            if not errors.empty:
                sec(f"⚠️ חריגות validation ({len(errors)})",
                    meta="אי-התאמה בין סוג דלק לסוג כלי")
                cols = [c for c in ["date", "matched_tool_name", "matched_license_num",
                                      "fuel_type", "validation_note", "total_cost"]
                        if c in errors.columns]
                heb = {"date": "תאריך", "matched_tool_name": "כלי",
                       "matched_license_num": "רישוי", "fuel_type": "סוג דלק בתנועה",
                       "validation_note": "תיאור החריגה", "total_cost": "₪"}
                disp_e = errors[cols].copy()
                if "total_cost" in disp_e.columns:
                    disp_e["total_cost"] = pd.to_numeric(disp_e["total_cost"],
                                                          errors="coerce").round(0)
                disp_e.columns = [heb.get(c, c) for c in cols]
                display_dataframe(disp_e, use_container_width=True, hide_index=True)

            # ── Drill-down: בחר כלי לראות את כל תנועות הדלק שלו ──
            if not matched.empty:
                sec("בחר כלי לפירוט תנועות")
                tools_for_pick = sorted([
                    (int(r["matched_license_num"]), str(r["matched_tool_name"]))
                    for _, r in matched.drop_duplicates("matched_license_num").iterrows()
                    if pd.notna(r["matched_license_num"])
                ])
                if tools_for_pick:
                    options = ["— בחר —"] + [f"{lic} · {name}" for lic, name in tools_for_pick]
                    picked = st.selectbox("כלי", options,
                                            key=f"fuel_drill_{project_meta['project_id']}")
                    if picked and picked != "— בחר —":
                        pick_lic = int(picked.split(" · ", 1)[0])
                        tool_tx = matched[matched["matched_license_num"] == pick_lic]
                        cols = [c for c in ["date", "month", "source_kind", "supplier",
                                              "invoice_num", "fuel_type", "qty_liters",
                                              "total_cost", "description", "match_note",
                                              "validation_note"]
                                if c in tool_tx.columns]
                        heb = {"date": "תאריך", "month": "חודש", "source_kind": "מקור",
                               "supplier": "ספק", "invoice_num": "חשבונית",
                               "fuel_type": "סוג דלק", "qty_liters": "ליטרים",
                               "total_cost": "₪", "description": "פרטים",
                               "match_note": "הערת התאמה", "validation_note": "validation"}
                        disp_t = tool_tx[cols].copy()
                        for c in ("qty_liters", "total_cost"):
                            if c in disp_t.columns:
                                disp_t[c] = pd.to_numeric(disp_t[c],
                                                            errors="coerce").round(0)
                        disp_t.columns = [heb.get(c, c) for c in cols]
                        display_dataframe(disp_t.sort_values("תאריך" if "תאריך" in disp_t.columns else disp_t.columns[0]),
                                     use_container_width=True, hide_index=True)

    # ── מקור 2 (לשעבר היה ראשי): דוח רכש פריטים - חשבונית-לחשבונית ──
    sec("חשבוניות סולר ברמת פירוט", meta="מדוח רכש פריטים")
    inv = load_fuel_invoices_data(project_meta["project_id"])
    if inv.empty:
        ins("blue", "ℹ️", "אין דוח רכש פריטים",
            "טען קובץ <code>data/fuel_invoices.xlsx</code> (פלט 'דוח רכש לפי פריט' מחשבשבת) "
            "כדי לראות חשבוניות סולר עם ליטרים, מחיר לליטר, ספק וקוד אתר.")
    else:
        total_l = float(inv["liters"].sum())
        total_c = float(inv["total_cost"].sum())
        avg_p = total_c / total_l if total_l > 0 else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("חשבוניות", str(len(inv)))
        c2.metric("ליטרים", format_number(total_l))
        c3.metric("סה\"כ עלות", f"₪{total_c:,.0f}")
        c4.metric("₪ ממוצע לליטר", format_decimal(avg_p))

        # ─ סיכום לפי ספק ─
        with st.expander("לפי ספק", expanded=True):
            sup = summary_by_supplier(inv)
            sup.columns = ["ספק", "חשבוניות", "ליטרים", "סה\"כ (₪)", "₪/ל'"]
            display_dataframe(sup, use_container_width=True, hide_index=True)

        # ─ סיכום חודשי + זיהוי קפיצות מחיר ─
        with st.expander("לפי חודש (₪/ליטר) - לזיהוי קפיצות מחיר", expanded=True):
            mo = summary_by_month(inv)
            mo.columns = ["חודש", "חשבוניות", "ליטרים", "סה\"כ (₪)", "₪/ל'"]
            display_dataframe(mo, use_container_width=True, hide_index=True)
            # התראה אם יש קפיצה משמעותית
            if len(mo) >= 2:
                prices = mo["₪/ל'"].astype(float)
                if (prices.max() / prices.min()) > 1.2:
                    ins("amber", "⚠️", "קפיצה משמעותית במחיר",
                        f"מחיר נע בין ₪{prices.min():.2f} ל-₪{prices.max():.2f} "
                        f"({(prices.max()/prices.min()-1)*100:.0f}% הפרש). "
                        "בדוק חשבוניות גבוהות מול הספק.")

        # ─ פירוט חשבוניות ─
        with st.expander(f"פירוט {len(inv)} חשבוניות"):
            disp = inv[["date", "invoice_num", "supplier", "liters",
                          "price_per_liter", "total_cost", "item_description", "month"]].copy()
            disp["date"] = pd.to_datetime(disp["date"]).dt.strftime("%d/%m/%Y")
            disp["liters"] = disp["liters"].round(0)
            disp["price_per_liter"] = disp["price_per_liter"].round(2)
            disp["total_cost"] = disp["total_cost"].round(0)
            disp.columns = ["תאריך", "מס' חשבונית", "ספק", "ליטרים",
                            "₪/ל'", "סה\"כ (₪)", "פרטים", "חודש"]
            display_dataframe(disp.sort_values("תאריך", ascending=False),
                         use_container_width=True, hide_index=True)

    # ── מקור 2: חשבשבת כרטיס (חשבונות סולר) ──
    sec("חיובי סולר מכרטיס ההנהלה", meta="בדיקה צולבת עם דוח הרכש")
    fuel_chash = _filter_by_keywords(df, KEYWORD_CATEGORIES["fuel"])
    if "source" in fuel_chash.columns:
        fuel_chash = fuel_chash[fuel_chash["source"] == "chashbashevet"]
    if "amount" in fuel_chash.columns:
        fuel_chash = fuel_chash[fuel_chash["amount"] > 0]

    from core import control_db
    manual = control_db.list_rows("fuel_logs", project_meta["project_id"])

    total_chash = float(fuel_chash["amount"].sum()) if not fuel_chash.empty else 0
    total_manual_cost = float(manual["total_cost"].sum()) if not manual.empty and "total_cost" in manual.columns else 0
    total_manual_liters = float(manual["liters"].sum()) if not manual.empty and "liters" in manual.columns else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("מכרטיס הנהלה", format_currency(total_chash))
    c2.metric("מהזנה ידנית (ל')", format_number(total_manual_liters))
    c3.metric("מהזנה ידנית", format_currency(total_manual_cost))

    if not fuel_chash.empty:
        sec("קניות מחשבשבת")
        fp = fuel_chash.copy()
        if "description" in fp.columns:
            fp["invoice_num"] = fp["description"].apply(_extract_invoice_num)
        cols = [c for c in ["date", "supplier", "invoice_num", "description",
                            "amount", "month"] if c in fp.columns]
        heb = {"date": "תאריך", "supplier": "ספק", "invoice_num": "מס' חשבונית",
               "description": "פרטים", "amount": "סכום (₪)", "month": "חודש"}
        disp = fp[cols].copy().sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        if "סכום (₪)" in disp.columns:
            disp["סכום (₪)"] = disp["סכום (₪)"].round(0)
        display_dataframe(disp, use_container_width=True, hide_index=True)

        # קבץ לפי ספק
        with st.expander("חלוקה לפי ספק"):
            by_sup = fuel_chash.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
            by_sup.columns = ["ספק", "סה\"כ (₪)", "חשבוניות"]
            by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
            display_dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
                         use_container_width=True, hide_index=True)

    if not manual.empty:
        sec("קניות ידניות")
        cols = [c for c in ["date", "tool_name", "license_num", "driver", "supplier",
                            "invoice_num", "liters", "price_per_liter", "total_cost"]
                if c in manual.columns]
        heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
               "driver": "נהג", "supplier": "ספק", "invoice_num": "חשבונית",
               "liters": "ל'", "price_per_liter": "₪/ל'", "total_cost": "סה\"כ"}
        disp = manual[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)


# ─── סולר וכלים → שימוש בסולר ──────────────────────────────
def _append_fuel_total_row(disp: pd.DataFrame) -> pd.DataFrame:
    """מוסיף שורת סה״כ בתחתית טבלת תדלוקים — מסכם ליטרים.

    שומר על ה-dtype של כל עמודה (NaT לתאריך, NaN למספרי) כדי לא
    לשבור את ה-column_config formatting של st.dataframe.
    """
    if disp.empty:
        return disp
    total: dict = {}
    for col, dtype in disp.dtypes.items():
        if pd.api.types.is_datetime64_any_dtype(dtype):
            total[col] = pd.NaT
        elif pd.api.types.is_numeric_dtype(dtype):
            total[col] = float("nan")
        else:
            total[col] = None
    label_col = "שם כלי" if "שם כלי" in disp.columns else disp.columns[0]
    total[label_col] = f'סה״כ ({len(disp):,} תדלוקים)'
    if "ליטרים" in disp.columns:
        total["ליטרים"] = float(pd.to_numeric(disp["ליטרים"], errors="coerce").sum())
    total_df = pd.DataFrame([total]).astype(
        {col: disp[col].dtype for col in disp.columns
         if pd.api.types.is_datetime64_any_dtype(disp[col].dtype)
         or pd.api.types.is_numeric_dtype(disp[col].dtype)},
    )
    return pd.concat([disp, total_df], ignore_index=True)


_FUEL_TRACKER_COL_HEB = {
    "date":         "תאריך",
    "site":         "אתר",
    "license_num":  "מס' רישוי",
    "tool_name":    "שם כלי",
    "owner":        "בעלים",
    "liters":       "כמות סולר",
    "engine_hours": "קריאת שעות מנוע",      # מצטבר, לא ל-חישוב
    "work_hours":   "שעות עבודה מחושבות",   # ספירת שעות מנוע = delta
    "lph_display":  "ליטר/שעה",
    "status":       "סטטוס חריגה",
    "notes":        "הערות",
}

# סדר העמודות לתצוגה (לפי spec 7)
_FUEL_TRACKER_COL_ORDER = [
    "date", "site", "license_num", "tool_name", "owner",
    "liters", "engine_hours", "work_hours", "lph_display",
    "status", "notes",
]

# מחרוזת לתצוגה במקום NaN/None
_DASH = "—"


def _is_bad_meter_status(status) -> bool:
    """True אם הסטטוס מצביע על קריאת מונה לא תקינה.

    במקרים כאלה לא רוצים להציג ליטר/שעה (אפילו לא 0.0) כי הוא נובע
    מקריאת מונה פגומה ולא מצריכה אמיתית.
    """
    if pd.isna(status):
        return False
    s = str(status)
    return any(
        marker in s
        for marker in (
            "🔴",                        # כל החריגות האדומות
            "ספירת שעות שלילית",          # מונה חזר אחורה
            "לא ניתן לחשב",               # אין delta תקין
            "קריאת מונה",                 # קפיצה גדולה / לא תקינה
            "אין נתון ליטרים",
        )
    )


def _fmt_num(v, decimals: int = 0) -> str:
    """ממיר מספר ל-string מפורמט. NaN/None → '—'."""
    if v is None or pd.isna(v):
        return _DASH
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _DASH
    if decimals == 0:
        return f"{int(round(f)):,}"
    return f"{f:,.{decimals}f}"


def _fmt_text(v) -> str:
    """ממיר טקסט ל-string. None/NaN/'nan'/'NaT'/'' → '—'."""
    if v is None:
        return _DASH
    try:
        if pd.isna(v):
            return _DASH
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "nat", "<na>"):
        return _DASH
    return s


def _format_fuel_tracker_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """ממיר DataFrame של fuel_tracker לטבלת תצוגה.

    - מסנן לעמודות הרלוונטיות, שם עברי
    - שורות עם קריאת מונה לא תקינה → ליטר/שעה ריק (לא 0.0 מטעה)
    - **השאר נומרי** — ה-cast ל-strings קורה ב-_finalize_display_strings
      אחרי append של שורת סה״כ.
    """
    if df.empty:
        return df
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for c in _FUEL_TRACKER_COL_ORDER:
        if c not in out.columns:
            out[c] = pd.NA

    # blank lph_display לכל שורה עם status שמצביע על מונה פגום
    if "status" in out.columns and "lph_display" in out.columns:
        bad_mask = out["status"].apply(_is_bad_meter_status)
        out.loc[bad_mask, "lph_display"] = pd.NA

    out = out[_FUEL_TRACKER_COL_ORDER].copy()
    out.columns = [_FUEL_TRACKER_COL_HEB.get(c, c) for c in _FUEL_TRACKER_COL_ORDER]
    return out


# מיפוי עמודות תצוגה → פורמט (decimals; -1 = text-only)
_DISPLAY_FMT = {
    "כמות סולר":           1,
    "קריאת שעות מנוע":     0,
    "שעות עבודה מחושבות":  1,
    "ליטר/שעה":            2,
    "שעות מנוע":           0,
    "ליטרים":              1,
}


def _finalize_display_strings(disp: pd.DataFrame) -> pd.DataFrame:
    """שלב סופי לפני display_dataframe — ממיר כל תא ל-string תצוגה.

    NaN/None/'' → '—' באופן עקבי בכל העמודות (נומריות וטקסטואליות).
    מבוצע אחרי append של שורת סה״כ כדי לא לפגוע ב-SUM.
    """
    if disp.empty:
        return disp
    out = disp.copy()
    for col in out.columns:
        if col in _DISPLAY_FMT:
            decimals = _DISPLAY_FMT[col]
            out[col] = out[col].apply(lambda v: _fmt_num(v, decimals=decimals))
        elif col == "תאריך":
            # תאריך — נשמור כ-datetime כדי שה-DateColumn יציג בפורמט נכון
            # רק NaT → "—"
            continue
        else:
            out[col] = out[col].apply(_fmt_text)
    return out


def _subtab_fuel_usage(df: pd.DataFrame, project_meta: dict) -> None:
    """שימוש בסולר בפועל — קורא מ-"מעקב סולר וטיפולים — כלי צמה" (יומן סולר)."""
    from pipeline import load_fuel_tracker_data

    sec("שימוש בסולר", meta="תדלוקים בפועל לכלים (יומן שטח)")

    project_id = project_meta["project_id"]

    # ── מקור 1: דוח תדלוקים בפועל (Pointer/Delkan) — מ-master.parquet ──
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    has_solar = not solar.empty and "liters" in solar.columns and \
                float(solar["liters"].fillna(0).sum()) > 0

    # ── מקור 2: יומן שטח עשיר — מ-fuel_tracker.parquet ──
    tracker = load_fuel_tracker_data(project_id)
    has_tracker = not tracker.empty
    total_tracker_l = float(tracker["liters"].fillna(0).sum()) if has_tracker else 0.0
    total_solar_l = float(solar["liters"].fillna(0).sum()) if has_solar else 0.0

    # ── סיכום עליון (spec 13, 14) ──
    c1, c2, c3 = st.columns(3)
    with c1:
        if has_solar:
            st.metric("מדוח תדלוקים בפועל (ל')", format_number(total_solar_l))
        else:
            # spec: אין קובץ דוח תדלוקים → להציג "לא נטען" (לא 0)
            st.markdown(
                '<div style="background:#F8FAFC;border:1px solid #CBD5E1;'
                'border-radius:8px;padding:10px 14px;text-align:center">'
                '<div style="font-size:11px;color:#64748B;font-weight:600">'
                'מדוח תדלוקים בפועל (ל\')</div>'
                '<div style="font-size:20px;font-weight:700;color:#475569;'
                'margin-top:6px">לא נטען</div>'
                '</div>',
                unsafe_allow_html=True,
            )
    with c2:
        if has_tracker:
            st.metric("שימוש מיומן שטח (ל')", format_number(total_tracker_l))
        else:
            st.markdown(
                '<div style="background:#FEF3C7;border:1px solid #FCD34D;'
                'border-radius:8px;padding:10px 14px;text-align:center">'
                '<div style="font-size:11px;color:#92400E;font-weight:600">'
                'שימוש מיומן שטח</div>'
                '<div style="font-size:14px;color:#78350F;margin-top:4px">'
                'אין נתונים מיומן שטח</div>'
                '</div>',
                unsafe_allow_html=True,
            )
    with c3:
        combined = total_solar_l + total_tracker_l
        st.metric("סה\"כ שימוש מחושב (ל')", format_number(combined))

    # ── ספירת שורות תקינות מול בעיתיות מ-fuel_tracker ──
    n_clean = n_problematic = 0
    clean_liters = problematic_liters = 0.0
    problematic_breakdown: dict = {}
    if has_tracker and "status" in tracker.columns:
        from core.fuel_tracker_loader import is_anomaly_status
        anom_mask = tracker["status"].apply(is_anomaly_status)
        n_problematic = int(anom_mask.sum())
        n_clean = len(tracker) - n_problematic
        problematic_liters = float(
            pd.to_numeric(tracker.loc[anom_mask, "liters"], errors="coerce").fillna(0).sum()
        )
        clean_liters = total_tracker_l - problematic_liters
        problematic_breakdown = dict(tracker.loc[anom_mask, "status"].value_counts())

    # ── סיכום מילולי מתחת ל-cards ──
    summary_parts = []
    if has_tracker:
        summary_parts.append(f"שימוש מיומן שטח = **{format_number(total_tracker_l)}** ל'")
    if has_solar:
        summary_parts.append(f"דוח תדלוקים בפועל = **{format_number(total_solar_l)}** ל'")
    else:
        summary_parts.append("דוח תדלוקים בפועל = **לא נטען**")
    if has_tracker or has_solar:
        summary_parts.append(f"סה\"כ שימוש מחושב = **{format_number(combined)}** ל'")
    if summary_parts:
        st.markdown(
            '<div style="background:#F0FDF4;border:1px solid #BBF7D0;'
            'border-radius:8px;padding:10px 14px;margin-top:6px;font-size:12px">'
            + ' &nbsp;·&nbsp; '.join(summary_parts) + '</div>',
            unsafe_allow_html=True,
        )

    # ── הפרדה ברורה: תקין vs בעיתי (spec 7, 8) ──
    if has_tracker and (n_clean or n_problematic):
        sec("הרכב נתוני התדלוק",
            meta="הפרדה בין שורות תקינות לשורות שדורשות בדיקה")
        rk1, rk2, rk3 = st.columns(3)
        with rk1:
            st.metric("✓ שורות תקינות", format_number(n_clean),
                      delta=f"{format_number(clean_liters)} ל'")
        with rk2:
            st.metric("⚠ שורות בעייתיות", format_number(n_problematic),
                      delta=f"{format_number(problematic_liters)} ל'")
        with rk3:
            ratio = (clean_liters / total_tracker_l * 100) if total_tracker_l else 0
            st.metric("% ליטרים מתוך תקינות", f"{ratio:.1f}%",
                      help="חלק הליטרים שמגיע משורות תקינות. ערך נמוך = להתבסס בעיקר על הקובץ למידע ולא על חישובים")
        if problematic_breakdown:
            breakdown_html = "<br>".join(
                f"• <code>{s}</code>: {c:,} שורות"
                for s, c in problematic_breakdown.items()
            )
            ins("amber", "⚠️",
                f"פירוט {n_problematic:,} השורות הבעייתיות:",
                breakdown_html + "<br><br>"
                "<b>שורות אלו לא נכללות בחישובי ליטר/שעה ממוצעים בטאב 'ניתוח'.</b> "
                "הן כן נספרות בסכום הליטרים הכולל (שכן הסולר אכן נצרך)."
                )

    # ── מידע על מקורות הנתונים (spec 12) ──
    if has_tracker:
        st.caption(
            "📋 **מקורות הנתונים בטבלה:**  "
            "ליטרים → עמודה 'כמות סולר (ל')'  ·  "
            "קריאת מונה → 'שעות מנוע'  ·  "
            "שעות עבודה בפועל → 'ספירת שעות מנוע'  ·  "
            "ליטר/שעה → 'צריכה מסוננת (ל'/ש')' (או 'צריכה לשעה' כ-fallback). "
            "**שעות מנוע** היא קריאת מונה מצטברת — לא משתמשים בה לחישוב צריכה."
        )

    # ── הטבלה הראשית: תדלוקים מיומן שטח (spec 7, 8, 9) ──
    if has_tracker:
        sec("תדלוקים מיומן שטח",
            meta=f"{len(tracker):,} שורות · מקובץ 'מעקב סולר וטיפולים — כלי צמה'")
        disp = _format_fuel_tracker_for_display(tracker.sort_values("date"))
        disp = _append_fuel_total_row(disp)
        # spec: NaN/None → "—" עקבי בכל העמודות
        disp = _finalize_display_strings(disp)
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── טבלת חריגות (spec 15) ──
    if has_tracker and "status" in tracker.columns:
        from core.fuel_tracker_loader import is_anomaly_status
        anom_mask = tracker["status"].apply(is_anomaly_status)
        anomalies = tracker[anom_mask]
        n_anom = len(anomalies)
        if n_anom > 0:
            sec(
                f"⚠ שורות הדורשות בדיקה ({n_anom:,})",
                meta="קריאת מונה ריקה / ספירה שלילית / קפיצה גדולה / צריכה לא הגיונית / חסר רישוי",
            )
            anom_summary = anomalies["status"].value_counts()
            ins(
                "amber", "⚠️",
                f"זוהו {n_anom:,} שורות מתוך {len(tracker):,} ({n_anom*100/len(tracker):.1f}%) הדורשות בדיקה ידנית.",
                "<br>".join(f"• <code>{s}</code>: {c}" for s, c in anom_summary.items()),
            )
            disp_anom = _format_fuel_tracker_for_display(anomalies.sort_values("date"))
            disp_anom = _finalize_display_strings(disp_anom)
            display_dataframe(disp_anom, use_container_width=True, hide_index=True)
        else:
            ins("green", "✓",
                "אין חריגות בנתוני התדלוק",
                f"כל {len(tracker):,} השורות עברו את בדיקות התקינות.")

    # ── הטבלה הישנה של "מדוח תדלוקים" — רק אם יש נתונים ──
    if has_solar:
        sec("תדלוקים מדוח תדלוקים בפועל (Pointer / Delkan)")
        cols = [c for c in ["date", "tool_name", "license_num", "liters", "engine_hours"]
                if c in solar.columns]
        disp = solar[cols].copy().sort_values("date" if "date" in cols else cols[0])
        heb = {"date": "תאריך", "tool_name": "שם כלי", "license_num": "מס' רישוי",
               "liters": "ליטרים", "engine_hours": "קריאת שעות מנוע"}
        disp.columns = [heb.get(c, c) for c in cols]
        disp = _append_fuel_total_row(disp)
        disp = _finalize_display_strings(disp)
        display_dataframe(disp, use_container_width=True, hide_index=True)

    # ── אם אין שום נתון ──
    if not has_tracker and not has_solar:
        ins("blue", "ℹ️",
            "אין נתוני שימוש בסולר",
            "וודא ש-`data/projects/<id>/מעקב סולר וטיפולים — כלי צמה.xlsx` קיים "
            "(או קבצי `solar.xlsx` במחיצות החודשיות), ולאחר מכן הרץ "
            "<code>python -c \"from pipeline import build_master; build_master()\"</code>.")


# ─── סולר וכלים → מלאי סולר (Step 4) ───────────────────────
def _render_purchase_vs_usage_summary(
    df: pd.DataFrame, project_meta: dict,
) -> None:
    """דוח התאמה חי: סה״כ קניות סולר vs סה״כ שימוש + פירוט חודשי.

    מציג:
      - 4 מטריקות עליונות: קניות (ל'), שימוש (ל'), הפרש (ל'), הפרש (₪)
      - טבלת התאמה חודשית
      - הסבר שקניות ושימוש לא חייבים להיות שווים (צובר / שיהוי חודשים)
    """
    from pipeline import load_fuel_tracker_data, load_fuel_invoices_data
    project_id = project_meta["project_id"]

    sec("📊 התאמה: קניות vs שימוש (בליטרים)",
        meta="קניות סולר מהכרטיס/חשבוניות מול שימוש מיומן שטח")

    # ── מקור A: קניות (ל') ──
    # עדיפות: fuel_invoices (יש ליטרים מפורשים); fallback: chashbashevet ₪ / מחיר ממוצע
    inv = load_fuel_invoices_data(project_id)
    purchases_per_month: dict = {}
    if not inv.empty and "liters" in inv.columns:
        for m, grp in inv.groupby("month"):
            purchases_per_month[m] = float(
                pd.to_numeric(grp["liters"], errors="coerce").fillna(0).sum()
            )
    total_purchases_l = sum(purchases_per_month.values())

    # ── מקור B: שימוש (ל') ──
    tracker = load_fuel_tracker_data(project_id)
    usage_per_month: dict = {}
    if not tracker.empty and "date" in tracker.columns and "liters" in tracker.columns:
        tr = tracker.copy()
        tr["date"] = pd.to_datetime(tr["date"], errors="coerce")
        tr["month"] = tr["date"].dt.strftime("%m-%Y")
        for m, grp in tr.groupby("month"):
            usage_per_month[m] = float(
                pd.to_numeric(grp["liters"], errors="coerce").fillna(0).sum()
            )
    total_usage_l = sum(usage_per_month.values())

    # ── מחיר ממוצע לליטר (מ-fuel_invoices אם יש; אחרת לא מחושב) ──
    avg_price = None
    if not inv.empty and "liters" in inv.columns and "total_cost" in inv.columns:
        liters_sum = pd.to_numeric(inv["liters"], errors="coerce").fillna(0).sum()
        cost_sum = pd.to_numeric(inv["total_cost"], errors="coerce").fillna(0).sum()
        if liters_sum > 0:
            avg_price = cost_sum / liters_sum

    # ── 4 מטריקות עליונות ──
    delta_l = total_purchases_l - total_usage_l
    delta_nis = (delta_l * avg_price) if avg_price else None

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if total_purchases_l > 0:
            st.metric("סה\"כ קניות (ל')", format_number(total_purchases_l))
        else:
            st.markdown(_na_card("סה\"כ קניות (ל')",
                                  "אין fuel_invoices.xlsx"), unsafe_allow_html=True)
    with c2:
        if total_usage_l > 0:
            st.metric("סה\"כ שימוש (ל')", format_number(total_usage_l))
        else:
            st.markdown(_na_card("סה\"כ שימוש (ל')",
                                  "אין fuel_tracker"), unsafe_allow_html=True)
    with c3:
        if total_purchases_l > 0 and total_usage_l > 0:
            color = "green" if delta_l >= 0 else "red"
            st.metric(
                "הפרש (ל')",
                f"{delta_l:+,.0f}",
                help="חיובי = מצטבר מלאי / שימוש בחודש אחר; שלילי = שימוש > קניות בתקופה",
            )
        else:
            st.markdown(_na_card("הפרש (ל')", "—"), unsafe_allow_html=True)
    with c4:
        if delta_nis is not None:
            st.metric(
                "הפרש (₪)",
                f"{delta_nis:+,.0f}",
                help=f"לפי מחיר ממוצע: ₪{avg_price:.2f}/ל'",
            )
        else:
            st.markdown(_na_card("הפרש (₪)", "אין מחיר ממוצע"),
                       unsafe_allow_html=True)

    # ── הסבר ──
    ins("blue", "ℹ️",
        "קניות ושימוש לא חייבים להיות שווים",
        "קניות יכולות להיכנס למיכל/צובר בחודש מסוים והשימוש מהן יכול להתחלק "
        "על פני חודשים מאוחרים יותר. ההפרש מייצג שינוי מלאי + תנועות שטרם שויכו.")

    # ── טבלת התאמה חודשית ──
    all_months = sorted(set(purchases_per_month.keys()) | set(usage_per_month.keys()))
    if all_months:
        sec("התאמה חודשית")
        rows = []
        for m in all_months:
            p = purchases_per_month.get(m, 0)
            u = usage_per_month.get(m, 0)
            d = p - u
            d_nis = (d * avg_price) if avg_price else None
            rows.append({
                "חודש": m,
                "קניות (ל')": p if p > 0 else None,
                "שימוש (ל')": u if u > 0 else None,
                "הפרש (ל')": d if (p > 0 or u > 0) else None,
                "הפרש (₪)": round(d_nis, 0) if d_nis is not None and (p > 0 or u > 0) else None,
            })
        recon = pd.DataFrame(rows)
        # שורת סה״כ
        total_row = {
            "חודש": "סה\"כ",
            "קניות (ל')": total_purchases_l if total_purchases_l > 0 else None,
            "שימוש (ל')": total_usage_l if total_usage_l > 0 else None,
            "הפרש (ל')": delta_l if (total_purchases_l > 0 or total_usage_l > 0) else None,
            "הפרש (₪)": round(delta_nis, 0) if delta_nis is not None else None,
        }
        recon = pd.concat([recon, pd.DataFrame([total_row])], ignore_index=True)
        # format strings → "—" for None
        for col in ("קניות (ל')", "שימוש (ל')", "הפרש (ל')", "הפרש (₪)"):
            recon[col] = recon[col].apply(
                lambda v: "—" if pd.isna(v) else f"{float(v):,.0f}"
            )
        display_dataframe(recon, use_container_width=True, hide_index=True)


def _na_card(label: str, message: str) -> str:
    """HTML של כרטיס 'לא נטען'/'—' בעיצוב neutral."""
    return (
        f'<div style="background:#F8FAFC;border:1px solid #CBD5E1;'
        f'border-radius:8px;padding:10px 14px;text-align:center">'
        f'<div style="font-size:11px;color:#64748B;font-weight:600">{label}</div>'
        f'<div style="font-size:16px;font-weight:700;color:#475569;'
        f'margin-top:6px">{message}</div>'
        f'</div>'
    )


def _subtab_fuel_inventory(df: pd.DataFrame, project_meta: dict) -> None:
    """מאזן מלאי סולר עם הפרדה לפי סוג דלק + טופס הזנה + reconciliation.

    סולר צמ"ה: מאזן מלאי מלא (פתיחה + קניות - שימושים = סגירה).
    בנזין / חשמל / סולר רכבים: רק קניות vs שימוש, ללא מלאי פיזי.
    """
    from core import control_db
    from pipeline import load_fuel_invoices_data
    project_id = project_meta["project_id"]

    # ── דוח התאמה: קניות vs שימוש (חדש, בראש הטאב) ──
    _render_purchase_vs_usage_summary(df, project_meta)

    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    if "main_category" in chash.columns:
        fuel_chash = chash[chash["main_category"] == "דלק ואנרגיה"]
    else:
        fuel_chash = pd.DataFrame()

    # ── סיכום עליון לפי סוג דלק ──
    sec("סיכום מלאי וקניות לפי סוג דלק (₪)")
    FUEL_TYPES = [
        ("סולר צמ\"ה", "🚜", True),    # has_inventory=True
        ("סולר רכבים", "🚗", False),
        ("בנזין רכבים", "⛽", False),
        ("טעינת חשמל רכבים", "🔌", False),
    ]
    cols_top = st.columns(4)
    for col, (ftype, icon, has_inv) in zip(cols_top, FUEL_TYPES):
        sub = fuel_chash[fuel_chash["sub_category"] == ftype] if not fuel_chash.empty else pd.DataFrame()
        purchases = float(sub["net_amount"].sum()) if not sub.empty and "net_amount" in sub.columns else 0
        n = len(sub)
        with col:
            bg = "#F0FDF4" if has_inv else "#F8FAFC"
            inv_label = "📦 עם מאזן מלאי" if has_inv else "ללא מלאי פיזי"
            st.markdown(
                f"""<div style="background:{bg};border:1px solid #BBF7D0;border-radius:10px;
                padding:14px;text-align:center">
                  <div style="font-size:22px">{icon}</div>
                  <div style="font-size:11px;font-weight:700;color:#475569;margin:4px 0">{ftype}</div>
                  <div style="font-size:18px;font-weight:800;color:#0F172A">₪{purchases:,.0f}</div>
                  <div style="font-size:10px;color:#64748B;margin-top:4px">{n} תנועות · {inv_label}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    # ── סולר צמ"ה: מאזן מלאי מלא ──
    sec("📦 סולר צמ\"ה - מאזן מלאי", meta="פתיחה + קניות - שימושים = סגירה")

    # 1. טופס הזנת מלאי
    with st.expander("➕ הזנת מלאי פתיחה/סגירה (סולר צמ\"ה)"):
        with st.form(f"finv_form_{project_id}", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                inv_month = st.text_input("חודש (MM-YYYY) *")
                inv_fuel = st.selectbox("סוג דלק", ["סולר צמ\"ה", "סולר רכבים", "בנזין רכבים"],
                                          help="לסולר צמ\"ה רלוונטי במיוחד")
            with fc2:
                inv_open = st.number_input("מלאי פתיחה (ל')",
                                             min_value=0.0, step=100.0, value=0.0)
                inv_close = st.number_input("מלאי סגירה (ל')",
                                              min_value=0.0, step=100.0, value=0.0)
            with fc3:
                inv_tank = st.text_input("מזהה מיכל (אופציונלי)")
                inv_notes = st.text_input("הערות")
            if st.form_submit_button("💾 שמור מלאי", type="primary",
                                       use_container_width=True):
                ok, msg = control_db.save_fuel_inventory(
                    project_id, inv_month.strip(), fuel_type=inv_fuel,
                    opening_l=inv_open if inv_open > 0 else None,
                    closing_l=inv_close if inv_close > 0 else None,
                    tank_id=inv_tank.strip(), notes=inv_notes.strip(),
                )
                if ok:
                    st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(msg)

    # 2. חישוב מאזן (מ-SQLite + xlsx + נתונים מחושבים)
    inv_db = control_db.list_fuel_inventory(project_id, fuel_type="סולר צמ\"ה")
    inv_xlsx = _collect_fuel_inventory(project_id)
    # union: SQLite גובר על xlsx על אותו חודש
    inv_all = inv_db[["month", "opening_l", "closing_l"]].copy() if not inv_db.empty else \
              pd.DataFrame(columns=["month", "opening_l", "closing_l"])
    if not inv_xlsx.empty:
        new = inv_xlsx[~inv_xlsx["month"].isin(inv_all["month"])]
        inv_all = pd.concat([inv_all, new], ignore_index=True, sort=False)

    if inv_all.empty:
        ins("blue", "ℹ️", "אין נתוני מלאי",
            "הזן מלאי פתיחה/סגירה בטופס לעיל. בלי זה אי אפשר לחשב מאזן.")
    else:
        # קניות סולר צמ"ה לפי חודש (₪ + ליטרים מ-fuel_invoices אם קיים)
        zmh_chash = fuel_chash[fuel_chash["sub_category"] == "סולר צמ\"ה"] if not fuel_chash.empty else pd.DataFrame()
        inv_book = load_fuel_invoices_data(project_id)

        purchases_l_per_month = {}
        if not inv_book.empty and "liters" in inv_book.columns:
            for m, grp in inv_book.groupby("month"):
                purchases_l_per_month[m] = float(grp["liters"].sum())
        else:
            # fallback - infer liters מ-chashbashevet ₪ / avg price
            zmh_total = float(zmh_chash["net_amount"].sum()) if not zmh_chash.empty else 0
            solar_total_l = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0
            avg_p = zmh_total / solar_total_l if solar_total_l > 0 else 6.94
            if not zmh_chash.empty:
                for m, grp in zmh_chash.groupby("month"):
                    purchases_l_per_month[m] = float(grp["net_amount"].sum()) / avg_p

        # שימושים - מ-solar.xlsx
        usage_l_per_month = {}
        if not solar.empty and "liters" in solar.columns:
            for m, grp in solar.groupby("month"):
                usage_l_per_month[m] = float(grp["liters"].sum())

        from core.fuel_inventory import compute_balance
        balance = compute_balance(inv_all, purchases_l_per_month, usage_l_per_month)
        if balance.empty:
            st.caption("מאזן ריק.")
        else:
            disp = balance.copy()
            disp.columns = ["חודש", "פתיחה (ל')", "קניות (ל')", "שימושים (ל')",
                            "סגירה צפויה", "סגירה בפועל", "הפרש", "סטטוס"]
            display_dataframe(disp, use_container_width=True, hide_index=True)
            n_bad = int((balance["status"] == "חוסר").sum())
            if n_bad:
                ins("amber", "⚠️", f"{n_bad} חודשים עם חוסר במלאי",
                    "ההפרש מצביע על שימוש לא מתועד או פחת חריג.")

    # ── הצגת קניות + שימושים לכל סוג דלק (גם ללא מאזן) ──
    sec("קניות vs שימוש (לכל סוג דלק)")
    rows = []
    for ftype, icon, has_inv in FUEL_TYPES:
        sub_chash = fuel_chash[fuel_chash["sub_category"] == ftype] if not fuel_chash.empty else pd.DataFrame()
        purchases_nis = float(sub_chash["net_amount"].sum()) if not sub_chash.empty and "net_amount" in sub_chash.columns else 0

        # שימוש בליטרים - רק לסולר צמ"ה (מ-solar.xlsx)
        if ftype == "סולר צמ\"ה" and not solar.empty:
            usage_l = float(solar["liters"].sum()) if "liters" in solar.columns else 0
        else:
            usage_l = None  # אין מקור אמין לבנזין/חשמל

        rows.append({
            "סוג דלק": f"{icon} {ftype}",
            "קניות (₪)": round(purchases_nis, 0),
            "שימוש (ל')": round(usage_l, 0) if usage_l is not None else "—",
            "תנועות": len(sub_chash),
            "מאזן פיזי": "✓ רלוונטי" if has_inv else "— לא נדרש",
        })
    display_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Reconciliation: chashbashevet vs fuel_invoices ──
    sec("התאמה בין מקורות", meta="כרטיס הנהלה ↔ דוח רכש פריטים ↔ יומן שטח")
    zmh_chash_total = float(fuel_chash[fuel_chash["sub_category"] == "סולר צמ\"ה"]["net_amount"].sum()) \
        if "sub_category" in fuel_chash.columns and not fuel_chash.empty else 0
    inv_book = load_fuel_invoices_data(project_id)
    book_total = float(inv_book["total_cost"].sum()) if not inv_book.empty and "total_cost" in inv_book.columns else 0
    field_solar_l = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0

    recon_data = [
        {"מקור": "כרטיס הנהלה (74327 סולר צמ\"ה)", "₪": round(zmh_chash_total, 0),
         "ליטרים": "—", "תנועות": int((fuel_chash["sub_category"] == "סולר צמ\"ה").sum()) if "sub_category" in fuel_chash.columns else 0},
        {"מקור": "דוח רכש פריטים (Book1)", "₪": round(book_total, 0),
         "ליטרים": round(float(inv_book["liters"].sum()), 0) if not inv_book.empty and "liters" in inv_book.columns else 0,
         "תנועות": len(inv_book)},
        {"מקור": "יומן שטח (solar.xlsx)", "₪": "—",
         "ליטרים": round(field_solar_l, 0), "תנועות": len(solar)},
    ]
    display_dataframe(pd.DataFrame(recon_data), use_container_width=True, hide_index=True)

    # ── מסקנה ניהולית: ההפרש בין הרישום החשבונאי לדוח הרכש ──
    if zmh_chash_total and book_total:
        diff_abs = book_total - zmh_chash_total
        diff_pct = abs(diff_abs) / zmh_chash_total * 100
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("רכש מכרטיס הנהלה", format_currency(zmh_chash_total))
        kpi2.metric("רכש לפי דוח פריטים", format_currency(book_total))
        kpi3.metric("הפרש", format_currency(diff_abs),
                     delta=f"{diff_pct:.1f}%",
                     delta_color="inverse")

        # נתוני מלאי חסרים → אסור להציג "התאמה טובה"
        has_inventory = not inv_all.empty if 'inv_all' in dir() else False
        if not has_inventory:
            ins("blue", "ℹ️", "התאמה חלקית - חסרים נתוני מלאי",
                "ההשוואה כעת היא רק בין סכומי הרכש (כרטיס מול דוח). "
                "ללא מלאי פתיחה/סגירה אי אפשר לחשב פערי שימוש אמיתיים.")
        elif diff_pct > 10:
            ins("red", "🚨", f"סטייה גדולה: {diff_pct:.1f}%",
                f"הפרש של {format_currency(diff_abs)} בין הרישום לחיובים. "
                "דורש בדיקה — ייתכן שחסר חשבונית או נרשם פעמיים.")
        elif diff_pct > 5:
            ins("amber", "⚠️", f"סטייה בינונית: {diff_pct:.1f}%",
                f"הפרש של {format_currency(diff_abs)}. "
                "סבירה בגלל מע\"מ או טווח תאריכים — מומלץ לבדוק את החודש האחרון.")
        else:
            ins("green", "✓", f"סטייה סבירה: {diff_pct:.1f}%",
                f"הפרש של {format_currency(diff_abs)} בלבד — בטווח המקובל.")
    else:
        ins("blue", "ℹ️", "אי אפשר לחשב התאמה",
            "חסרים נתונים: ודא שיש סכומי רכש מכרטיס ההנהלה וגם מדוח הרכש.")

    # ── רשימת רישומי מלאי קיימים (כולל עריכה/מחיקה) ──
    if not inv_db.empty:
        sec("רישומי מלאי שמורים")
        disp = inv_db[["month", "fuel_type", "tank_id", "opening_l",
                         "closing_l", "notes"]].copy()
        disp.columns = ["חודש", "סוג דלק", "מזהה מיכל",
                        "פתיחה (ל')", "סגירה (ל')", "הערות"]
        display_dataframe(disp, use_container_width=True, hide_index=True)
        del_id = st.number_input("מחק רישום לפי ID", min_value=0, step=1, value=0,
                                    key=f"del_finv_{project_id}")
        if st.button("🗑 מחק רישום", key=f"del_finv_btn_{project_id}",
                       disabled=del_id <= 0):
            if control_db.delete_fuel_inventory(int(del_id), project_id):
                st.success("נמחק")
                st.rerun()
            else:
                st.error("רישום לא נמצא")


# ─── סולר וכלים → צריכת סולר לפי כלי ───────────────────────
def _subtab_consumption_per_tool(df: pd.DataFrame, project_meta: dict) -> None:
    """ל'/ש' בפועל לכל כלי, מול תקן עליון."""
    sec("צריכת סולר לפי כלי", meta="ל'/ש' מול תקן עליון × 1.15")
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    if solar.empty or hours.empty:
        ins("blue", "ℹ️", "נדרשים גם דוח תדלוקים וגם דוח שעות", "")
        return
    from core import solar_loader, hours_loader
    from pipeline import _load_tools_registry
    sm = solar_loader.aggregate_by_tool_month(solar)
    hm = hours_loader.aggregate_by_tool_month(hours)
    excess = anomaly_detector.detect_solar_excess(sm, hm, _load_tools_registry())
    if excess.empty:
        ins("green", "✓", "כל הכלים בתקן", "אין חריגות צריכת סולר.")
    else:
        disp = excess.copy()
        disp["actual_lph"] = disp["actual_lph"].round(1)
        disp["damage_estimate_nis"] = disp["damage_estimate_nis"].round(0)
        disp.columns = ["מס' רישוי", "שם כלי", "חודש", "סה\"כ ל'",
                        "סה\"כ שעות", "ל'/ש' בפועל", "תקן עליון",
                        "חריגה (ל')", "נזק (₪)", "חומרה"]
        display_dataframe(disp, use_container_width=True, hide_index=True)


# ─── סולר → התאמת דלק לכלים (item 6) ───────────────────────
def _subtab_fuel_matching(df: pd.DataFrame, project_meta: dict) -> None:
    """תת-טאב ייעודי להתאמת תנועות דלק לכלים.

    מחבר את 3 מקורות הדלק (chashbashevet, solar.xlsx, fuel_invoices)
    דרך core.equipment_matcher + מוסיף UI לשיוך ידני שנשמר ל-JSON
    בפרויקט.
    """
    from core.equipment_matcher import enrich_fuel_transactions
    from core import fuel_assignments
    from pipeline import _load_tools_registry, load_fuel_invoices_data

    project_id = project_meta["project_id"]
    equipment = _load_tools_registry()
    if equipment.empty:
        ins("amber", "⚠️", "אין כלים ברשימה",
            "צריך לפחות כלי אחד ברשימת הכלים כדי לבצע התאמה. "
            "עבור לטאב '🚜 כלים → רשימת כלים' והשתמש בכפתור "
            "'הפק רשימה אוטומטית' או הוסף ידנית.")
        return

    # ── איסוף כל מקורות הדלק ──
    all_fuel = []
    solar_rows = df[df["source"] == "solar"] if "source" in df.columns else pd.DataFrame()
    if not solar_rows.empty:
        s = solar_rows.copy()
        s["source_kind"] = "solar"
        s = s.rename(columns={"liters": "qty_liters"})
        if "amount" in s.columns:
            s["total_cost"] = s["amount"]
        else:
            s["total_cost"] = 0
        all_fuel.append(s)

    inv = load_fuel_invoices_data(project_id)
    if not inv.empty:
        i = inv.copy()
        i["source_kind"] = "fuel_invoices"
        i = i.rename(columns={"item_description": "description",
                                "liters": "qty_liters"})
        if "total_cost" not in i.columns:
            i["total_cost"] = 0
        all_fuel.append(i)

    # קח חיובי דלק מהכרטיס ההנהלה (74317 / 74327)
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else pd.DataFrame()
    if not chash.empty and "main_category" in chash.columns:
        fuel_chash = chash[chash["main_category"] == "דלק ואנרגיה"].copy()
        if not fuel_chash.empty:
            fuel_chash["source_kind"] = "chashbashevet"
            fuel_chash["qty_liters"] = 0  # אין ליטרים בכרטיס
            fuel_chash["total_cost"] = fuel_chash["amount"]
            all_fuel.append(fuel_chash)

    if not all_fuel:
        ins("blue", "ℹ️", "אין נתוני דלק בפרויקט",
            "טען דוח תדלוקים (solar.xlsx), חשבוניות דלק או תנועות "
            "דלק מכרטיס ההנהלה.")
        return

    combined = pd.concat(all_fuel, ignore_index=True, sort=False)
    # נרמל עמודות חסרות
    for col in ("description", "license_num", "tool_name", "fuel_type",
                  "qty_liters", "total_cost", "supplier", "date", "month"):
        if col not in combined.columns:
            combined[col] = None

    # ── הרצת ה-matcher ──
    enriched = enrich_fuel_transactions(
        combined, equipment,
        license_col="license_num", tool_name_col="tool_name",
        description_col="description", fuel_type_col="fuel_type",
    )

    # ── החלת שיוכים ידניים (override) ──
    enriched = fuel_assignments.apply_to_enriched(enriched, project_id, equipment)

    # ── KPIs ──
    n_total = len(enriched)
    n_matched = int((enriched["matched_by"] != "unmatched").sum())
    n_manual = int((enriched["_manual_override"] == True).sum())
    n_high = int((enriched["match_confidence"] == "high").sum())
    n_unmatched = n_total - n_matched
    match_pct = (n_matched / n_total * 100) if n_total else 0

    mk1, mk2, mk3, mk4 = st.columns(4)
    mk1.metric("סה\"כ תנועות דלק", format_number(n_total))
    mk2.metric("הותאמו", format_number(n_matched),
                 delta=f"{match_pct:.0f}%")
    mk3.metric("שיוך ידני", format_number(n_manual))
    mk4.metric("לא משויכות", format_number(n_unmatched),
                 delta=f"-{n_unmatched/n_total*100:.0f}%" if n_total else None,
                 delta_color="inverse")

    # ── verdict ──
    if n_total == 0:
        pass
    elif n_unmatched == 0:
        ins("green", "✓", "כל תנועות הדלק מותאמות לכלים",
            "אין פעולה נדרשת.")
    elif match_pct >= 80:
        ins("green", "✓", f"כיסוי טוב: {match_pct:.0f}%",
            f"{n_unmatched} תנועות לא משויכות נשארו לטיפול ידני "
            "בטבלה למטה.")
    elif match_pct >= 50:
        ins("amber", "⚠️", f"כיסוי בינוני: {match_pct:.0f}%",
            f"{n_unmatched} תנועות דורשות שיוך ידני. "
            "ייתכן שחסרים כלים ברשימת הכלים.")
    else:
        ins("red", "🚨", f"כיסוי נמוך: {match_pct:.0f}%",
            f"{n_unmatched} מתוך {n_total} תנועות לא הותאמו. "
            "מומלץ להוסיף כלים חסרים לרשימה לפני המשך הניתוח.")

    # ── תנועות לא משויכות + שיוך ידני ──
    unmatched = enriched[enriched["matched_by"] == "unmatched"].copy()
    if not unmatched.empty:
        sec("תנועות דלק לא משויכות",
            meta=f"{len(unmatched)} תנועות — שייך ידנית או הוסף כלי חדש")

        # אגרגציה לפי description/supplier — קצר וטוב יותר מאלפי שורות
        from core.fuel_assignments import row_hash as _rh
        unmatched["row_hash"] = unmatched.apply(
            lambda r: _rh(r.get("date"), r.get("supplier"),
                            r.get("total_cost") or r.get("amount"),
                            r.get("description")),
            axis=1,
        )

        # אם יותר מ-30 שורות לא משויכות — מציג את הגדולות ביותר
        if len(unmatched) > 30:
            st.caption(f"מציג 30 תנועות עם הסכום הגבוה ביותר "
                       f"(מתוך {len(unmatched)} סה\"כ).")
            unmatched_show = unmatched.nlargest(30, "total_cost", keep="first")
        else:
            unmatched_show = unmatched

        # אופציות שיוך
        tool_options: dict[str, int | None] = {"— בחר כלי —": None}
        for _, eq in equipment.iterrows():
            lic = eq.get("license_num")
            tname = eq.get("tool_name", "")
            if pd.notna(lic):
                tool_options[f"{int(lic)} · {tname}"] = int(lic)

        for _, row in unmatched_show.iterrows():
            h = row["row_hash"]
            date_str = pd.to_datetime(row.get("date"), errors="coerce")
            date_str = date_str.strftime("%d/%m/%Y") if pd.notna(date_str) else "—"
            sup = row.get("supplier") or "—"
            desc = row.get("description") or ""
            cost = float(row.get("total_cost") or 0)
            label = f"📅 {date_str} · 🏪 {sup} · {format_currency(cost)} · {desc[:60]}"
            with st.expander(label, expanded=False):
                if desc:
                    st.caption(f"פרטים מלאים: {desc}")
                ext = row.get("extracted_license")
                if pd.notna(ext) and ext:
                    st.info(f"🔍 חולץ מהפרטים: רישוי **{int(ext)}** — "
                            "לא נמצא ברשימת הכלים. הוסף אותו כדי לאפשר התאמה אוטומטית.")
                c1, c2 = st.columns([3, 1])
                with c1:
                    pick = st.selectbox(
                        "שייך לכלי",
                        list(tool_options.keys()),
                        key=f"fmatch_sel_{h}",
                    )
                with c2:
                    if pick != "— בחר כלי —" and st.button(
                        "💾 שייך", key=f"fmatch_btn_{h}",
                        use_container_width=True, type="primary",
                    ):
                        fuel_assignments.assign(
                            project_id, h, tool_options[pick],
                            notes="שיוך ידני מטאב התאמה",
                        )
                        st.success(f"✅ שויך ל-{pick}")
                        st.cache_data.clear()
                        st.rerun()

    # ── רכבים שזוהו בתיאור אבל חסרים ברשימת הכלים ──
    from core.equipment_matcher import unmatched_vehicle_candidates
    candidates = unmatched_vehicle_candidates(enriched)
    if not candidates.empty:
        sec("🆕 רכבים שחולצו מהתיאור אבל חסרים ברשימה",
            meta=f"{len(candidates)} מספרי רישוי")
        ins("blue", "💡", "הוסף אותם לרשימת הכלים",
            "המערכת חילצה את המספרים מהפרטים אך לא מצאה אותם ברשימה. "
            "עבור לטאב '🚜 כלים → רשימת כלים' והוסף אותם כדי "
            "שהדלק יתאים אוטומטית בעתיד.")
        disp = candidates.copy()
        disp.columns = ["מס' רישוי", "תיאור לדוגמה", "תנועות",
                        "סה\"כ ₪"]
        display_dataframe(disp)

    # ── שיוכים ידניים קיימים — לעריכה / ביטול ──
    existing = fuel_assignments.list_assignments(project_id)
    if not existing.empty:
        sec("📋 שיוכים ידניים שמורים",
            meta=f"{len(existing)} שיוכים — לחץ '↩ בטל שיוך' לכל שורה כדי להחזיר אותה לרשימת התנועות הלא משויכות")

        # קישור row_hash → פרטי התנועה המקורית, לתצוגה
        # נבנה lookup מ-enriched כדי להראות לאיזה תנועה השיוך מתייחס.
        enriched["_hash"] = enriched.apply(
            lambda r: fuel_assignments.row_hash(
                r.get("date"), r.get("supplier"),
                r.get("total_cost") or r.get("amount"),
                r.get("description"),
            ),
            axis=1,
        )
        enriched_lookup = enriched.set_index("_hash", drop=False)

        eq_idx = equipment.set_index("license_num", drop=False)

        for _, assign_row in existing.iterrows():
            h = assign_row["row_hash"]
            lic = int(assign_row["license_num"])
            tool_label = (
                f"{lic} · {eq_idx.loc[lic, 'tool_name']}"
                if lic in eq_idx.index else f"{lic} (לא ברשימת הכלים)"
            )
            created_at = pd.to_datetime(assign_row["assigned_at"],
                                            errors="coerce")
            created_str = created_at.strftime("%d/%m/%Y %H:%M") \
                if pd.notna(created_at) else "—"

            # פרטי התנועה המקורית — אם מצאנו אותה
            tx_label = ""
            tx_amount_str = ""
            tx_date_str = ""
            tx_supplier = ""
            tx_desc = ""
            if h in enriched_lookup.index:
                tx_row = enriched_lookup.loc[h]
                if isinstance(tx_row, pd.DataFrame):
                    tx_row = tx_row.iloc[0]
                tx_date_str = pd.to_datetime(tx_row.get("date"),
                                                 errors="coerce")
                tx_date_str = tx_date_str.strftime("%d/%m/%Y") \
                    if pd.notna(tx_date_str) else "—"
                tx_supplier = str(tx_row.get("supplier") or "—")
                tx_desc = str(tx_row.get("description") or "")
                tx_amount = float(tx_row.get("total_cost")
                                  or tx_row.get("amount") or 0)
                tx_amount_str = format_currency(tx_amount)
                tx_label = f" · 📅 {tx_date_str} · 🏪 {tx_supplier} · {tx_amount_str}"

            label = f"🔗 → {tool_label}{tx_label}"

            with st.expander(label, expanded=False):
                st.caption(f"שויך בתאריך: {created_str}")
                if tx_desc:
                    st.caption(f"תיאור התנועה: {tx_desc}")
                if assign_row.get("notes"):
                    st.caption(f"הערות: {assign_row['notes']}")

                # מנגנון 2-שלבי לאישור הביטול
                confirm_key = f"unassign_confirm_{h}"
                if not st.session_state.get(confirm_key):
                    if st.button("↩ בטל שיוך", key=f"unassign_btn_{h}",
                                   use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()
                else:
                    st.warning(
                        f"❓ האם אתה בטוח שברצונך לבטל את השיוך ל-**{tool_label}**? "
                        "התנועה תחזור לרשימת 'תנועות לא משויכות' וכל הסיכומים "
                        "יחושבו מחדש."
                    )
                    yc, nc = st.columns(2)
                    with yc:
                        if st.button("✅ כן, בטל שיוך", key=f"unassign_yes_{h}",
                                       use_container_width=True, type="primary"):
                            # 1. הסר את השיוך מה-JSON
                            fuel_assignments.unassign(project_id, h)
                            # 2. רישום ל-audit_log
                            try:
                                from core import db
                                db.log_event("unlink_fuel_to_tool", {
                                    "project_id": project_id,
                                    "row_hash": h,
                                    "previous_license": lic,
                                    "previous_tool": tool_label,
                                    "tx_date": tx_date_str,
                                    "tx_supplier": tx_supplier,
                                    "tx_amount": tx_amount_str,
                                })
                            except Exception:
                                # audit נכשל לא צריך לחסום את הביטול
                                pass
                            st.session_state.pop(confirm_key, None)
                            st.cache_data.clear()
                            st.success("✅ השיוך בוטל בהצלחה")
                            st.rerun()
                    with nc:
                        if st.button("✖ ביטול", key=f"unassign_no_{h}",
                                       use_container_width=True):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()


# ─── סולר וכלים → טיפולים ואחזקה ───────────────────────────
def _subtab_maintenance(df: pd.DataFrame, project_meta: dict) -> None:
    """אחזקות מחשבשבת + טיפולים מ-site_tracking + הזנה ידנית."""
    sec("אחזקות - מחשבשבת")
    maint = _filter_by_keywords(df, KEYWORD_CATEGORIES["maintenance"])
    if "source" in maint.columns:
        maint = maint[maint["source"] == "chashbashevet"]
    if "amount" in maint.columns:
        maint = maint[maint["amount"] > 0]
    if maint.empty:
        st.caption("אין תנועות אחזקה.")
    else:
        st.metric("סה\"כ אחזקה", format_currency(float(maint['amount'].sum())))
        by_sup = maint.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_sup.columns = ["ספק / מוסך", "סה\"כ (₪)", "תנועות"]
        by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
        display_dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

    from pipeline import load_site_tracking_data
    project_id = project_meta["project_id"]
    site_data = load_site_tracking_data(project_id)
    treatments = site_data.get("treatments", pd.DataFrame())
    if not treatments.empty:
        sec("מרווחי טיפול וטיפול הבא")
        cols = [c for c in ["tool_name", "license_num", "engine_hours_current",
                            "last_service_date", "service_interval",
                            "next_service_hours", "hours_until_service"]
                if c in treatments.columns]
        heb = {"tool_name": "שם כלי", "license_num": "מס' רישוי",
               "engine_hours_current": "שעות נוכחיות",
               "last_service_date": "תאריך טיפול",
               "service_interval": "מרווח", "next_service_hours": "שעות לטיפול הבא",
               "hours_until_service": "נותרו"}
        disp = treatments[cols].copy()
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

    from core import control_db
    manual = control_db.list_rows("maintenance_logs", project_id)
    if not manual.empty:
        sec("טיפולים מהזנה ידנית")
        cols = [c for c in ["date", "tool_name", "license_num", "treatment_type",
                            "garage_supplier", "cost", "engine_hours",
                            "next_service_hours", "invoice_num"] if c in manual.columns]
        heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
               "treatment_type": "סוג טיפול", "garage_supplier": "מוסך",
               "cost": "עלות", "engine_hours": "ש\"מ", "next_service_hours": "טיפול הבא",
               "invoice_num": "חשבונית"}
        disp = manual[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)


# ─── סולר וכלים → עלות כלי לשעה ────────────────────────────
def _subtab_cost_per_hour(df: pd.DataFrame, project_meta: dict) -> None:
    """חישוב עלות לשעת כלי: סולר + אחזקה / שעות עבודה."""
    sec("עלות כלי לשעה", meta="(סולר + אחזקה) / שעות עבודה")
    project_id = project_meta["project_id"]
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    fuel_chash = _filter_by_keywords(df, KEYWORD_CATEGORIES["fuel"])
    if "amount" in fuel_chash.columns:
        fuel_chash = fuel_chash[fuel_chash["amount"] > 0]
    maint = _filter_by_keywords(df, KEYWORD_CATEGORIES["maintenance"])
    if "amount" in maint.columns:
        maint = maint[maint["amount"] > 0]

    total_l = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0
    total_fuel_cost = float(fuel_chash["amount"].sum()) if not fuel_chash.empty else 0
    total_maint_cost = float(maint["amount"].sum()) if not maint.empty else 0
    avg_price = total_fuel_cost / total_l if total_l > 0 else 0

    if hours.empty:
        ins("blue", "ℹ️", "אין שעות עבודה",
            "ללא שעות אי אפשר לחשב עלות לשעה. טען <code>hours.xlsx</code> או הזן ידנית.")
        return

    # Cost per tool: fuel proportional to liters + maintenance attributed
    by_tool_hours = hours.groupby(["license_num", "tool_name"])["work_hours"].sum().reset_index()
    by_tool_solar = solar.groupby("license_num")["liters"].sum().reset_index() \
        if not solar.empty else pd.DataFrame(columns=["license_num", "liters"])
    merged = by_tool_hours.merge(by_tool_solar, on="license_num", how="left").fillna(0)

    # Approximate fuel cost per tool = liters_per_tool * avg_price
    merged["fuel_cost"] = (merged["liters"] * avg_price).round(0)
    # Allocate maintenance proportionally to work_hours (simple model)
    total_hours_all = float(merged["work_hours"].sum())
    if total_hours_all > 0 and total_maint_cost > 0:
        merged["maint_cost"] = (merged["work_hours"] / total_hours_all *
                                  total_maint_cost).round(0)
    else:
        merged["maint_cost"] = 0
    merged["total_cost"] = merged["fuel_cost"] + merged["maint_cost"]
    merged["cost_per_hour"] = merged.apply(
        lambda r: round(r["total_cost"] / r["work_hours"], 0) if r["work_hours"] > 0 else 0,
        axis=1,
    )

    disp = merged.sort_values("cost_per_hour", ascending=False)
    disp.columns = ["מס' רישוי", "שם כלי", "סה\"כ שעות",
                    "סה\"כ ליטרים", "עלות סולר (₪)", "עלות אחזקה (₪)",
                    "סה\"כ עלות (₪)", "₪ לשעה"]
    display_dataframe(disp, use_container_width=True, hide_index=True)
    st.caption("עלות אחזקה מחולקת באופן יחסי לשעות העבודה - מודל פשוט. "
               "לדיוק מלא, נדרש שדה license_num בכל חשבונית אחזקה.")


# ─── תרגום תוויות קטגוריה ─────────────────────────────────
def _label_he(key: str) -> str:
    return {
        "salary": "עובדים ושכר",
        "fuel": "סולר ודלק",
        "maintenance": "אחזקות (רכב/כלים)",
        "subcontractors": "קבלני משנה",
        "materials": "חומרים",
        "rentals": "שכירות ציוד",
        "insurance": "ביטוחים",
        "other": "אחר",
        "OTHER": "אחר",
    }.get(key, key)
