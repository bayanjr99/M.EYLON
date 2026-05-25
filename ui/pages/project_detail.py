"""דף ייעודי לפרויקט בודד - 9 טאבים, כל הנתונים מסוננים לפי project_id."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import analytics, anomaly_detector, project_aggregator
from ui.components import empty_state, ins, kpi_block, render_kpi_group, sec


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
    if abs(v) >= 1_000_000:
        return f"₪{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"₪{v/1_000:.0f}K"
    return f"₪{v:,.0f}"


def render_project_detail(df_master: pd.DataFrame, project_meta: dict) -> None:
    """מסך פרויקט: header + 9 טאבים. כל הטאבים מסוננים ל-project_id."""
    project_id = project_meta["project_id"]
    project_name = project_meta.get("project_name", project_id)
    client = project_meta.get("client_name") or project_meta.get("notes") or "—"
    # תרגום סטטוס לעברית להצגה
    _STATUS_HE = {"active": "פעיל", "paused": "מושהה", "closed": "סגור",
                  "on_hold": "מושהה", "completed": "הושלם"}
    status_raw = project_meta.get("status", "active")
    status = _STATUS_HE.get(str(status_raw).lower(), str(status_raw))

    # ── Back button + Header ─────────────────────────────────
    back_col, header_col = st.columns([1, 6])
    with back_col:
        if st.button("← חזרה לרשימה", key="back_to_list", use_container_width=True):
            st.session_state.pop("selected_project_id", None)
            st.rerun()
    with header_col:
        st.markdown(
            f"""<div style="display:flex;align-items:center;gap:12px;
            padding:8px 16px;background:linear-gradient(135deg,#F0FDF4,#FFFFFF);
            border-radius:10px;border:1px solid var(--brand-primary-mid)">
              <i class="ti ti-buildings" style="font-size:22px;color:var(--brand-primary)"></i>
              <div style="flex:1;min-width:0">
                <div style="font-size:15px;font-weight:800;color:var(--ink-strong);
                  line-height:1.2">{project_name}</div>
                <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">
                  לקוח: <b>{client}</b> · סטטוס: <b>{status}</b> · ID: <code>{project_id}</code>
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
            f"font-family:monospace;color:#7F1D1D;direction:ltr;text-align:left'>"
            f"<b>אבחון:</b><br>"
            f"CWD: {os.getcwd()}<br>"
            f"master.parquet path: {MASTER_PARQUET}<br>"
            f"exists: {master_exists}, size: {master_size:,} bytes<br>"
            f"master rows total: {len(df_master):,}<br>"
            f"project_ids in master: {all_ids}<br>"
            f"looking for project_id: <b>{project_id!r}</b><br>"
            f"</div>"
        )
        empty_state(
            icon="ti-database-off",
            title=f"אין עדיין נתונים לפרויקט {project_name}",
            body_html=(
                diag +
                "כדי לטעון נתונים:"
                "<ul>"
                f"<li>שים קבצים ב-<code>data/projects/{project_id}/&lt;MM-YYYY&gt;/</code></li>"
                "<li>הקבצים: <code>balance.xlsx</code> (מאזן), "
                "<code>chashbashevet.xlsx</code> (כרטיס הנהלה), "
                "<code>solar.xlsx</code>, <code>hours.xlsx</code></li>"
                "<li>הרץ: <code>python -c \"from pipeline import build_master; build_master()\"</code></li>"
                "<li>חזור לרשימה ופתח שוב את הפרויקט</li>"
                "</ul>"
            ),
        )
        return

    summary = project_aggregator.project_summary(df_master, project_id)

    # ── Period header: scope + months + tx count ──
    months_str = ", ".join(summary["months"]) if summary["months"] else "—"
    period_html = (
        f'<div class="period-header">'
        f'<span>📅 <b>{len(summary["months"])} חודשים</b>: {months_str}'
        f'<span class="sep">·</span> {summary["num_transactions"]:,} תנועות'
        f'<span class="sep">·</span> {summary["num_suppliers"]} ספקים</span>'
        f'<span class="tag">תמונת פרויקט</span>'
        f'</div>'
    )
    st.markdown(period_html, unsafe_allow_html=True)

    # ── ADMIN MODE: ייבוא/תקציב/בדיקות פותחים תצוגה נפרדת ──
    admin_view = st.session_state.get("admin_view")
    if admin_view:
        if st.button("← חזרה לטאבים הראשיים", key="back_from_admin",
                       use_container_width=False):
            st.session_state.pop("admin_view", None)
            st.rerun()
        if admin_view == "import":
            sub = st.tabs(["ייבוא קבצים", "היסטוריית ייבוא", "גיבוי וייצוא"])
            with sub[0]:
                from ui.pages.import_data import render_import_page
                from pipeline import list_available_projects
                render_import_page(list_available_projects())
            with sub[1]:
                _subtab_import_history(project_meta)
            with sub[2]:
                _subtab_backup_export(project_meta)
        elif admin_view == "budget":
            from ui.pages.budget import render_budget_tab
            render_budget_tab(df, project_meta)
        elif admin_view == "qa":
            _tab_qa(df, project_meta)
        return

    # ── HEADER: 3 כפתורי ניהול (לא טאבים) ──
    adm1, adm2, adm3, _ = st.columns([1, 1, 1, 4])
    with adm1:
        if st.button("📁 ייבוא נתונים", key="admin_import",
                       use_container_width=True):
            st.session_state["admin_view"] = "import"
            st.rerun()
    with adm2:
        if st.button("📈 תקציב מול ביצוע", key="admin_budget",
                       use_container_width=True):
            st.session_state["admin_view"] = "budget"
            st.rerun()
    with adm3:
        if st.button("🔍 בדיקות וחריגות", key="admin_qa",
                       use_container_width=True):
            st.session_state["admin_view"] = "qa"
            st.rerun()

    # ── 5 טאבים ראשיים בלבד ──
    tabs = st.tabs([
        "📊 סקירה כללית",
        "💰 כספים",
        "⛽ סולר",
        "🕒 שעות עבודה",
        "🚜 כלים",
    ])

    with tabs[0]:
        _tab_overview(df, summary)

    with tabs[1]:
        # כספים: 4 sub-tabs
        sub = st.tabs(["הכנסות", "הוצאות", "ספקים", "פירוט תנועות"])
        with sub[0]:
            _tab_income(df)
        with sub[1]:
            _tab_expenses(df)
        with sub[2]:
            _subtab_suppliers_finance(df, project_meta)
        with sub[3]:
            _tab_transactions(df)

    with tabs[2]:
        # סולר: 4 sub-tabs (עם הזנה ידנית בכל אחד)
        sub = st.tabs(["קניות סולר", "שימוש בסולר", "סיכום מלאי", "ניתוח"])
        with sub[0]:
            _subtab_fuel_purchases(df, project_meta)
            with st.expander("➕ הזנה ידנית של קניות סולר"):
                from ui.pages.field_data_entry import (
                    _render_fuel_quick_form, _render_sub_tab,
                )
                _render_fuel_quick_form(project_id)
                _render_sub_tab("fuel_logs", project_id, None, None)
        with sub[1]:
            _subtab_fuel_usage(df, project_meta)
        with sub[2]:
            _subtab_fuel_inventory(df, project_meta)
        with sub[3]:
            _subtab_consumption_per_tool(df, project_meta)

    with tabs[3]:
        # שעות עבודה: 3 sub-tabs (עם הזנה ידנית בכל אחד)
        sub = st.tabs(["שעות עבודה כלים", "שעות עובדים", "שעות קבלני משנה"])
        with sub[0]:
            _subtab_equipment_hours(df, project_meta)
            with st.expander("➕ הזנה ידנית של שעות עבודה כלים"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("equipment_work_logs", project_id, None, None)
        with sub[1]:
            _tab_employees(df, project_meta)
            with st.expander("➕ הזנה ידנית של שעות עובדים"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("employee_work_logs", project_id, None, None)
        with sub[2]:
            _subtab_contractors_field(df, project_meta)
            with st.expander("➕ הזנה ידנית של שעות קבלני משנה"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("contractor_work_logs", project_id, None, None)

    with tabs[4]:
        # כלים: 4 sub-tabs
        sub = st.tabs(["רשימת כלים", "פעילות כלים", "עלויות כלי", "ניתוח כלי"])
        with sub[0]:
            from ui.pages.field_data_entry import _render_tools_management
            _render_tools_management()
        with sub[1]:
            _tab_vehicles_tools(df, project_meta)
        with sub[2]:
            _subtab_maintenance(df, project_meta)
            with st.expander("➕ הזנה ידנית של טיפולים ואחזקה"):
                from ui.pages.field_data_entry import _render_sub_tab
                _render_sub_tab("maintenance_logs", project_id, None, None)
        with sub[3]:
            _subtab_cost_per_hour(df, project_meta)


# ─── Tab 1: סקירה כללית ─────────────────────────────────────
def _tab_overview(df: pd.DataFrame, summary: dict) -> None:
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

    # ── מגמה חודשית: הכנסות מול הוצאות ──
    sec("מגמה חודשית", meta="הכנסות מול הוצאות")
    trend = analytics.monthly_trend(df)
    if trend.empty:
        st.caption("אין מספיק חודשים להצגת מגמה.")
    else:
        disp = trend.copy()
        disp["רווח %"] = (
            (disp["total_income"] - disp["total_expenses"]) / disp["total_income"] * 100
        ).where(disp["total_income"] > 0).round(1)
        disp = disp[["month", "total_income", "total_expenses", "balance", "רווח %"]]
        disp.columns = ["חודש", "הכנסות", "הוצאות", "יתרה", "רווח %"]
        for c in ("הכנסות", "הוצאות", "יתרה"):
            disp[c] = disp[c].round(0)
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── Top 10 הוצאות + Top 10 ספקים ──
    chash_exp = df[(df["source"] == "chashbashevet") & (df["amount"] > 0)] \
        if "source" in df.columns else df.iloc[0:0]
    if not chash_exp.empty:
        c1, c2 = st.columns(2)
        with c1:
            sec("Top 10 הוצאות", meta="לפי קטגוריה")
            top_cat = chash_exp.groupby("category")["amount"].sum().nlargest(10).round(0).reset_index()
            top_cat.columns = ["קטגוריה", "סה\"כ (₪)"]
            st.dataframe(top_cat, use_container_width=True, hide_index=True)
        with c2:
            sec("Top 10 ספקים", meta="לפי סכום")
            top_sup = (chash_exp[chash_exp["supplier"].fillna("") != ""]
                        .groupby("supplier")["amount"].sum().nlargest(10).round(0).reset_index())
            top_sup.columns = ["ספק", "סה\"כ (₪)"]
            st.dataframe(top_sup, use_container_width=True, hide_index=True)


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
    """הכנסות = רק שורות מחשבונות הכנסה (927/951/7367 או category=='הכנסות').

    מסנן רק מסעיפי הכנסות אמיתיים - לא חשבונות אחרים שיש בתיאור שלהם
    את המילה 'הכנסות' (כדי לא להכניס בטעות תנועות הוצאה).
    """
    from core.chashbashevet_loader import INCOME_ACCOUNTS
    if "source" in df.columns:
        chash = df[df["source"] == "chashbashevet"]
    else:
        chash = df

    # סינון קשיח: רק חשבונות הכנסה (לפי מספר חשבון או category)
    mask_acct = chash["account_num"].isin(INCOME_ACCOUNTS) if "account_num" in chash.columns else False
    mask_cat = (chash["category"] == "הכנסות") if "category" in chash.columns else False
    income_all = chash[mask_acct | mask_cat]

    if income_all.empty:
        ins("blue", "ℹ️", "אין הכנסות מתועדות",
            "הכנסות מזוהות אך ורק לפי חשבונות {927, 951, 7367} או category='הכנסות'. "
            "ודא שהמאזן/כרטיס ההנהלה כולל אותם.")
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
        st.dataframe(monthly, use_container_width=True, hide_index=True)

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
    st.dataframe(disp, use_container_width=True, hide_index=True)

    ins("blue", "ℹ️", "סטטוס גבייה",
        "סטטוס שולם/פתוח לא מנוטר אוטומטית מחשבשבת. לתצוגה מלאה - "
        "חבר קובץ <code>collections.xlsx</code> או מערכת CRM.")


# ─── Tab 3: הוצאות (עם drill-down) ──────────────────────────
def _tab_expenses(df: pd.DataFrame) -> None:
    sec("הוצאות לפי קטגוריה")
    # רק חשבשבת ורק חיובי (הוצאות בפועל)
    exp_df = df[(df["source"] == "chashbashevet")] if "source" in df.columns else df.iloc[0:0]
    exp_df = exp_df[exp_df["amount"] > 0] if "amount" in exp_df.columns else exp_df

    if exp_df.empty:
        ins("blue", "ℹ️", "אין הוצאות מתועדות", "טען קובץ chashbashevet.xlsx לחודש.")
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
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

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
            st.dataframe(disp, use_container_width=True, hide_index=True)


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
        st.caption("אין נתוני חשבונות שכר ב-chashbashevet.")
    else:
        by_acct = salary_df.groupby("account_name")["amount"].agg(["sum", "count"]).reset_index()
        by_acct.columns = ["חשבון", "סכום", "תנועות"]
        by_acct["סכום"] = by_acct["סכום"].round(0)
        st.dataframe(by_acct.sort_values("סכום", ascending=False),
                     use_container_width=True, hide_index=True)

    # ── רמת עובד בודד (מ-site_tracking) ──
    sec("עובדים - שעות יומיות", meta="מ-site_tracking.xlsx")
    if emp_hours.empty:
        ins("blue", "ℹ️", "אין נתוני שעות עובדים", "הוסף site_tracking.xlsx עם גליון 'שעות עבודה עובדים'.")
    else:
        per_emp = emp_hours.groupby("name").agg(
            ימי_עבודה=("date", "nunique"),
            סה_כ_שעות=("work_hours", "sum"),
        ).reset_index().sort_values("סה_כ_שעות", ascending=False)
        per_emp["סה_כ_שעות"] = per_emp["סה_כ_שעות"].round(1)
        per_emp.columns = ["שם עובד", "ימי עבודה", "סה\"כ שעות"]
        st.dataframe(per_emp, use_container_width=True, hide_index=True)

        # Drill-down per employee
        with st.expander("פירוט יומי לכל עובד"):
            cols = [c for c in ["date", "name", "start_time", "end_time",
                                "work_hours", "notes"] if c in emp_hours.columns]
            heb = {"date": "תאריך", "name": "שם", "start_time": "התחלה",
                   "end_time": "סיום", "work_hours": "שעות", "notes": "הערות"}
            disp = emp_hours[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── הזנות ידניות מ-SQLite ──
    if project_meta:
        sec("הזנות ידניות (control_db)", meta="מטאב 'עדכון נתוני שטח'")
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
            st.dataframe(agg, use_container_width=True, hide_index=True)


# ─── Tab 5: ספקים וקבלנים (עם site_tracking + סיווג) ───────
def _tab_suppliers(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    from pipeline import load_site_tracking_data
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None

    # ── 1. Top ספקים עם קטגוריה דומיננטית ──
    sec("Top 30 ספקים - עם קטגוריה אוטומטית")
    sup_cat = project_aggregator.suppliers_categorized(df, top_n=30)
    if sup_cat.empty:
        ins("blue", "ℹ️", "אין ספקים מתועדים", "ספקים מחולצים מ-'פרטים' בכרטיס ההנהלה.")
    else:
        disp = sup_cat.copy()
        disp.columns = ["ספק", "קטגוריה ראשית", "סה\"כ (₪)", "תנועות",
                        "מס' קטגוריות", "קטגוריות משניות"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

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
                st.dataframe(show, use_container_width=True, hide_index=True)

    sec("קבלני משנה - חיובים מחשבשבת")
    subs = _filter_by_keywords(df, KEYWORD_CATEGORIES["subcontractors"])
    if subs.empty:
        st.caption("לא זוהו תנועות תחת 'קבלני משנה'.")
    else:
        cols = [c for c in ["date", "supplier", "description", "amount"] if c in subs.columns]
        st.dataframe(subs[cols], use_container_width=True, hide_index=True)

    # ── קבלני משנה - שעות תפעוליות מ-site_tracking ──
    sec("קבלני משנה - שעות עבודה בשטח", meta="מ-site_tracking.xlsx")
    site_data = load_site_tracking_data(project_id) if project_id else {}
    sub_hours = site_data.get("subcontractors_hours", pd.DataFrame())
    if sub_hours.empty:
        st.caption("אין נתוני שעות קבלני משנה ב-site_tracking.")
    else:
        per_sub = sub_hours.groupby("name").agg(
            ימי_עבודה=("date", "nunique"),
            סה_כ_שעות=("work_hours", "sum"),
        ).reset_index().sort_values("סה_כ_שעות", ascending=False)
        per_sub["סה_כ_שעות"] = per_sub["סה_כ_שעות"].round(1)
        per_sub.columns = ["שם קבלן/משאית", "ימי עבודה", "סה\"כ שעות"]
        st.dataframe(per_sub, use_container_width=True, hide_index=True)

        with st.expander("פירוט יומי לקבלני משנה"):
            cols = [c for c in ["date", "name", "license_num", "start_time",
                                "end_time", "work_hours", "notes"] if c in sub_hours.columns]
            heb = {"date": "תאריך", "name": "שם", "license_num": "מס' רכב",
                   "start_time": "התחלה", "end_time": "סיום",
                   "work_hours": "שעות", "notes": "הערות"}
            disp = sub_hours[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── הזנות ידניות מ-SQLite ──
    if project_meta:
        sec("הזנות ידניות (control_db)")
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
            st.dataframe(disp, use_container_width=True, hide_index=True)


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
    c3.metric("₪ / ליטר", f"{avg_price:.2f}" if avg_price else "—")
    c4.metric("₪ / שעת עבודה", f"{cost_per_hour:,.0f}" if cost_per_hour else "—")
    st.caption(f"{num_fuelings} תדלוקים · {int(total_work_h):,} שעות עבודה")

    # ── מאזן מלאי (משלב fuel_inventory.xlsx אם קיים) ──
    sec("מאזן מלאי סולר", meta="מ-fuel_inventory.xlsx")
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
        st.caption("אין fuel_inventory.xlsx. הוסף קובץ עם עמודות "
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
            st.dataframe(disp, use_container_width=True, hide_index=True)
            n_bad = int((balance["status"] == "חוסר").sum())
            if n_bad:
                ins("amber", "⚠️", f"{n_bad} חודשים עם חוסר במלאי",
                    "ההפרש מצביע על שימוש לא מתועד או פחת חריג.")

    # ── קניות סולר לפי ספק ──
    sec("קניות סולר לפי ספק")
    if fuel_purchases.empty:
        st.caption("לא זוהו רכישות סולר ב-chashbashevet (חשבונות עם 'סולר'/'דלק').")
    else:
        by_sup = fuel_purchases.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_sup.columns = ["ספק", "סה\"כ (₪)", "חשבוניות"]
        by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
        st.dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
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
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── צריכה לפי רכב/כלי ──
    sec("צריכה לפי כלי", meta="מתוך solar.xlsx")
    if solar.empty:
        ins("blue", "ℹ️", "אין נתוני תדלוק", "טען <code>solar.xlsx</code> לחודש.")
    else:
        by_tool = solar.groupby(["license_num", "tool_name"])["liters"].agg(
            ["sum", "count"]
        ).reset_index()
        by_tool.columns = ["מס' רישוי", "שם כלי", "סה\"כ ליטרים", "תדלוקים"]
        by_tool["סה\"כ ליטרים"] = by_tool["סה\"כ ליטרים"].round(0)

        # הוסף עלות משוערת (משערך לפי avg_price)
        if avg_price > 0:
            by_tool["עלות משוערת (₪)"] = (by_tool["סה\"כ ליטרים"] * avg_price).round(0)
        st.dataframe(by_tool.sort_values("סה\"כ ליטרים", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט תדלוקים"):
            cols = [c for c in ["date", "tool_name", "license_num", "liters",
                                "engine_hours", "lph_calculated"]
                    if c in solar.columns]
            st.dataframe(solar[cols].sort_values("date"),
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
            st.dataframe(disp, use_container_width=True, hide_index=True)

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
        st.dataframe(by_supm.sort_values("סה\"כ (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט תנועות אחזקה"):
            cols = [c for c in ["date", "month", "account_name", "supplier",
                                "description", "amount"] if c in maint.columns]
            st.dataframe(maint[cols].sort_values("date" if "date" in cols else cols[0]),
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
            st.dataframe(disp, use_container_width=True, hide_index=True)
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

    if hours.empty and solar.empty:
        ins("blue", "ℹ️", "אין נתוני כלים",
            "טען <code>hours.xlsx</code> ו/או <code>solar.xlsx</code> לחודש.")
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

    # ── תצוגה מאוחדת ──
    sec("כל הכלים בפרויקט")
    n_tools = int(merged["license_num"].nunique())
    total_h = float(merged["total_hours"].sum())
    total_l = float(merged["total_liters"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("כלים פעילים", str(n_tools))
    c2.metric("סה\"כ שעות", f"{total_h:,.0f}")
    c3.metric("סה\"כ ליטרים", f"{total_l:,.0f}")
    c4.metric("עלות סולר משוערת", _fmt_money(float(merged["fuel_cost_est"].sum())))

    show_cols = ["license_num", "tool_name", "tool_type", "total_hours",
                 "work_days", "total_liters", "fueling_count",
                 "lph_actual", "norm_high", "fuel_cost_est", "over_norm"]
    show_cols = [c for c in show_cols if c in merged.columns]
    disp = merged[show_cols].copy()
    disp["total_hours"] = disp["total_hours"].round(1)
    if "total_liters" in disp.columns:
        disp["total_liters"] = disp["total_liters"].round(0)
    heb = {
        "license_num": "מס' רישוי", "tool_name": "שם כלי", "tool_type": "סוג",
        "total_hours": "שעות", "work_days": "ימי עבודה",
        "total_liters": "ליטרים", "fueling_count": "תדלוקים",
        "lph_actual": "ל'/ש'", "norm_high": "תקן", "fuel_cost_est": "עלות סולר משוערת (₪)",
        "over_norm": "מצב",
    }
    disp.columns = [heb.get(c, c) for c in show_cols]
    st.dataframe(disp.sort_values("עלות סולר משוערת (₪)" if "עלות סולר משוערת (₪)" in disp.columns else disp.columns[0],
                                  ascending=False),
                 use_container_width=True, hide_index=True)

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
            st.dataframe(disp, use_container_width=True, hide_index=True)
    else:
        st.caption("נדרשים גם solar.xlsx וגם hours.xlsx לזיהוי חריגות סולר.")

    # ── טיפולים ─ next service due (מ-site_tracking) ──
    from pipeline import load_site_tracking_data
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None
    site_data = load_site_tracking_data(project_id) if project_id else {}

    treatments = site_data.get("treatments", pd.DataFrame())
    if not treatments.empty:
        sec("מרווחי טיפול וטיפולים הבאים", meta="מ-site_tracking.xlsx")
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
        st.dataframe(disp, use_container_width=True, hide_index=True)

    log = site_data.get("treatments_log", pd.DataFrame())
    if not log.empty:
        sec("יומן טיפולים")
        st.dataframe(log, use_container_width=True, hide_index=True)

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
            st.dataframe(per_tool, use_container_width=True, hide_index=True)

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
            st.dataframe(disp, use_container_width=True, hide_index=True)

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
            st.dataframe(disp, use_container_width=True, hide_index=True)

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

    # פילטר חיפוש מקומי לטאב
    q = st.text_input("🔍 חיפוש בתנועות", key="tx_search",
                      placeholder="חפש ספק / חשבון / פרטים…")
    if q.strip():
        ql = q.strip().lower()
        mask = pd.Series(False, index=disp.index)
        for c in ("account_name", "supplier", "description"):
            if c in disp.columns:
                mask |= disp[c].astype(str).str.lower().str.contains(ql, na=False)
        disp = disp[mask]
        st.caption(f"{len(disp):,} תנועות תואמות")

    st.dataframe(disp, use_container_width=True, hide_index=True)


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


# ─── Tab 9: בדיקות וחריגות (QA) ─────────────────────────────
def _tab_qa(df: pd.DataFrame, project_meta: dict) -> None:
    """דוחות איכות נתונים - מה חסר/חשוד/לא מסווג."""
    from core import categorizer, storage
    from pipeline import list_available_months, PROJECTS_ROOT
    project_id = project_meta["project_id"]

    # ── חריגות בטיפול (persisted) ──
    sec("חריגות במעקב", meta="מ-data_quality_issues")
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
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("אין חודשים בתיקיית הפרויקט.")

    # ── 1. תנועות שנפלו לקטגוריות fallback (אחר/הוצאות תפעוליות וכו') ──
    sec("חשבונות לא מקוטלגים (נפלו ל-fallback)")
    unmapped = categorizer.report_unmapped(chash)
    if unmapped.empty:
        ins("green", "✓", "כל החשבונות מקוטלגים", "אין שום חשבון בקטגוריית fallback.")
    else:
        st.caption(f"{len(unmapped)} חשבונות. עדכן את category_mapping.xlsx כדי לסווג אותם נכון.")
        st.dataframe(unmapped, use_container_width=True, hide_index=True)
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
            st.dataframe(empty_sup[cols], use_container_width=True, hide_index=True)

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
            st.dataframe(disp, use_container_width=True, hide_index=True)

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
                st.dataframe(orphan_fuel[["date", "tool_name", "liters"]],
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
                st.dataframe(orphan_hrs[["date", "tool_name", "work_hours"]],
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
        st.dataframe(unclassified_income[cols], use_container_width=True, hide_index=True)

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
        st.dataframe(disp, use_container_width=True, hide_index=True)

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
        st.dataframe(disp, use_container_width=True, hide_index=True)

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
        st.dataframe(disp, use_container_width=True, hide_index=True)

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
        st.dataframe(rev_accounts.sort_values("נטו (₪)", ascending=False),
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
        st.dataframe(fuel_agg.sort_values("סכום נטו (₪)", ascending=False),
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
        st.dataframe(no_sup[cols], use_container_width=True, hide_index=True)

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
        st.dataframe(bad_sal[cols], use_container_width=True, hide_index=True)

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
            st.dataframe(joined.sort_values("מס' קטגוריות", ascending=False),
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
            st.dataframe(no_eq[cols].head(50), use_container_width=True, hide_index=True)
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
            st.dataframe(mismatch[cols], use_container_width=True, hide_index=True)

        # ── 17. inactive_equipment_has_fuel ──
        sec("דלק לכלי לא פעיל")
        inactive_alerts = enr[enr["validation_note"].astype(str).str.contains("לא פעיל", na=False)]
        if inactive_alerts.empty:
            ins("green", "✓", "כל הדלק לכלים פעילים", "")
        else:
            st.caption(f"{len(inactive_alerts)} תנועות דלק לכלים מושבתים.")
            cols = [c for c in ["date", "matched_tool_name", "matched_license_num",
                                  "fuel_type", "total_cost"] if c in inactive_alerts.columns]
            st.dataframe(inactive_alerts[cols], use_container_width=True, hide_index=True)

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
        st.dataframe(pd.DataFrame([{"מקור התאמה": k, "כמות": v} for k, v in stats.items()]),
                     use_container_width=True, hide_index=True)

    # ── 19. סטטיסטיקת fuel_rules: excel vs fallback ──
    sec("מקור סיווג דלק: fuel_rules.xlsx vs fallback")
    fuel_rows_all = chash[chash["main_category"] == "דלק ואנרגיה"] \
        if "main_category" in chash.columns else pd.DataFrame()
    if fuel_rows_all.empty:
        st.caption("אין תנועות דלק.")
    else:
        note_col = fuel_rows_all["classification_note"].astype(str)
        excel_count = int(note_col.str.contains("fuel_rules.xlsx").sum())
        fallback_count = int(note_col.str.contains("fallback").sum())
        manual_count = int(note_col.str.startswith("חשבון 74327").sum())  # legacy hardcoded
        unknown_count = len(fuel_rows_all) - excel_count - fallback_count - manual_count
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("מ-fuel_rules.xlsx", str(excel_count))
        c2.metric("מ-fallback hardcoded", str(fallback_count))
        c3.metric("ישן (legacy)", str(manual_count))
        c4.metric("אחר/לא ידוע", str(unknown_count))
        if fallback_count > 0:
            ins("amber", "⚠️", f"{fallback_count} תנועות סווגו ע\"י fallback hardcoded",
                "מומלץ להוסיף כללים מתאימים ל-fuel_rules.xlsx")

    # ── 14. ספקים עם סכומים חריגים (top 5 outliers ביחס לחציון) ──
    sec("ספקים עם סכומים חריגים", meta="חריגות סטטיסטיות (z-score > 3)")
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
                    st.dataframe(rows, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════
# SUB-TABS חדשים למבנה המקצועי (8 ראשיים)
# ════════════════════════════════════════════════════════════

# ─── כספים → חשבונות חשבשבת ─────────────────────────────────
def _subtab_accounts_rollup(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    """ריכוז לפי חשבון: חובה / זכות / יתרה / קטגוריה / האם ממופה +
    התאמה מול מאזן הבוחן אם קיים."""
    sec("ריכוז חשבונות חשבשבת")
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
    if chash.empty:
        ins("blue", "ℹ️", "אין נתוני חשבשבת", "טען כרטיס הנהלה.")
        return

    # Defensive: derive debit/credit from amount if columns are missing
    # (happens with master.parquet built before debit/credit were added to schema).
    chash = chash.copy()
    if "debit" not in chash.columns or "credit" not in chash.columns:
        chash["debit"] = chash["amount"].where(chash["amount"] > 0, 0)
        chash["credit"] = (-chash["amount"]).where(chash["amount"] < 0, 0)

    fallback_cats = {"אחר", "הוצאות תפעוליות", "הוצאות פרויקט", "הוצאות שכר/כלליות"}
    agg = chash.groupby(["account_num", "account_name"], dropna=False).agg(
        debit=("debit", "sum"),
        credit=("credit", "sum"),
        n_tx=("amount", "size"),
        category=("category", lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
    ).reset_index()
    agg["balance"] = agg["debit"] - agg["credit"]
    agg["mapped"] = agg["category"].apply(lambda c: "✓" if c not in fallback_cats else "✗")

    for col in ("debit", "credit", "balance"):
        agg[col] = agg[col].round(0)

    disp = agg[["account_num", "account_name", "debit", "credit", "balance",
                "n_tx", "category", "mapped"]].sort_values("balance", ascending=False)
    disp.columns = ["מס' חשבון", "שם חשבון", "סה\"כ חובה", "סה\"כ זכות",
                    "יתרה", "תנועות", "קטגוריה", "ממופה"]
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.caption(f"{len(agg)} חשבונות. {(agg['mapped'] == '✗').sum()} לא ממופים לקטגוריה.")

    # ── התאמת מאזן בוחן מול כרטיס ──
    if project_meta:
        from pipeline import load_project_balances
        from core.balance_loader import reconcile_with_ledger
        balances = load_project_balances(project_meta["project_id"])
        if not balances.empty:
            sec("התאמת מאזן בוחן מול כרטיס הנהלה", meta="לכל חודש בנפרד")
            months = sorted(balances["month"].dropna().unique())
            sel_month = st.selectbox("חודש", months, key="bal_recon_month")
            month_balance = balances[balances["month"] == sel_month][balance_OUTPUT_COLS]
            # Get ledger for that month (chashbashevet rows in that month)
            month_ledger = chash[chash["month"] == sel_month] if "month" in chash.columns else chash.iloc[0:0]
            # Need debit/credit columns - chash rows have them
            recon = reconcile_with_ledger(month_balance, month_ledger)
            if recon.empty:
                st.caption("אין נתונים לחישוב התאמה.")
            else:
                ok = int((recon["status"] == "✓ תואם").sum())
                mismatch = int((recon["status"] != "✓ תואם").sum())
                c1, c2 = st.columns(2)
                c1.metric("חשבונות תואמים", str(ok))
                c2.metric("חשבונות עם הפרש", str(mismatch),
                            delta=f"-{mismatch}" if mismatch else None,
                            delta_color="inverse" if mismatch else "normal")
                show = recon.copy()
                for c in ("balance_debit", "balance_credit", "ledger_debit",
                            "ledger_credit", "debit_diff", "credit_diff"):
                    if c in show.columns:
                        show[c] = show[c].round(0)
                show.columns = ["מס' חשבון", "שם חשבון", "מאזן-חובה", "מאזן-זכות",
                                  "כרטיס-חובה", "כרטיס-זכות",
                                  "הפרש חובה", "הפרש זכות", "סטטוס"]
                st.dataframe(show, use_container_width=True, hide_index=True)
                if mismatch:
                    ins("amber", "⚠️", f"{mismatch} חשבונות לא תואמים",
                        "ייתכן בגלל יתרת פתיחה שלא נכללת בכרטיס, או טעות באחד הקבצים.")


# constant used inside _subtab_accounts_rollup
balance_OUTPUT_COLS = ["sort_key", "account_num", "account_name",
                       "debit", "credit", "balance", "group"]


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
        ins("blue", "ℹ️", "אין נתוני חשבשבת", "טען כרטיס הנהלה.")
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
    k2.metric("הוצאות ספקים", f"₪{agg['net'].sum():,.0f}")
    k3.metric("ספק הכי יקר", str(most_expensive)[:18],
              help=f"₪{agg.iloc[0]['net']:,.0f}" if not agg.empty else "")
    k4.metric("קטגוריה הכי גדולה", str(biggest_cat))
    k5.metric("סה\"כ זיכויים", f"₪{total_credits:,.0f}")

    if n_unidentified:
        ins("amber", "⚠️", f"{n_unidentified} ספקים 'לא זוהה'",
            "תנועות הוצאה ללא שם ספק - בדוק בטאב QA → 'ספק לא מזוהה'.")

    # ── Top 10 ספקים (טבלה) ──
    sec("Top 10 ספקים", meta="לפי הוצאה נטו")
    top10 = agg.head(10)[["supplier_display", "main_cat", "net", "pct_total", "n_tx"]].copy()
    top10.columns = ["ספק", "קטגוריה ראשית", "סה\"כ נטו (₪)", "% מסך", "תנועות"]
    st.dataframe(top10, use_container_width=True, hide_index=True)

    # ── טבלת ספקים מלאה ──
    sec(f"כל הספקים ({len(agg)})")
    full = agg.copy()
    full.columns = ["ספק", "סה\"כ חובה", "סה\"כ זכות", "הוצאה נטו",
                    "תנועות", "חודשים", "קטגוריה ראשית", "תת-קטגוריה", "% מסך"]
    st.dataframe(full, use_container_width=True, hide_index=True)

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
    st.dataframe(by_grp, use_container_width=True, hide_index=True)

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
        cA.metric("חובה", f"₪{sum_debit:,.0f}")
        cB.metric("זכות (זיכויים)", f"₪{sum_credit:,.0f}")
        cC.metric("נטו", f"₪{sum_net:,.0f}")
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
        st.dataframe(disp, use_container_width=True, hide_index=True)

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


# ─── כספים → גבייה ─────────────────────────────────────────
def _subtab_collection_status(df: pd.DataFrame) -> None:
    """מצב גבייה - חשבוניות מכירה. כרגע placeholder כי אין שדה payment_status."""
    sec("מצב גבייה")
    income = df[(df["source"] == "chashbashevet") & (df["amount"] < 0)] \
        if "source" in df.columns else df.iloc[0:0]
    if income.empty:
        ins("blue", "ℹ️", "אין חשבוניות הכנסה",
            "חשבונות הכנסה (927/951/7367) ריקים בכרטיס ההנהלה.")
        return

    total = float(-income["amount"].sum())
    n_inv = int(len(income))
    c1, c2, c3 = st.columns(3)
    c1.metric("סה\"כ חשבוניות", str(n_inv))
    c2.metric("סה\"כ סכום", f"₪{total:,.0f}")
    c3.metric("יתרת לקוח (משוערת)", f"₪{total:,.0f}",
              help="כל החשבוניות נחשבות פתוחות כי אין שדה payment_status בנתוני המקור")

    cols = [c for c in ["date", "supplier", "description", "amount", "month"]
            if c in income.columns]
    disp = income[cols].copy()
    disp["amount"] = disp["amount"].abs().round(0)
    disp["status"] = "—"
    cols_rename = {"date": "תאריך", "supplier": "לקוח", "description": "פרטים",
                    "amount": "סכום (₪)", "month": "חודש"}
    disp.columns = [cols_rename.get(c, c) for c in cols] + ["סטטוס גבייה"]
    st.dataframe(disp.sort_values("תאריך"), use_container_width=True, hide_index=True)

    ins("amber", "ℹ️", "סטטוס גבייה לא מנוטר אוטומטית",
        "כרטיס ההנהלה לא כולל payment_status. לתצוגה אמיתית של פתוח/שולם - "
        "הוסף קובץ <code>collections.xlsx</code> או חבר ל-CRM.")


# ─── תפעול ושטח → יומן אתר ─────────────────────────────────
def _subtab_site_journal(project_meta: dict) -> None:
    """יומן אתר יומי - תיאור עבודה לכל יום. נשמר ב-SQLite."""
    sec("יומן אתר", meta="תיעוד יומי של מנהל העבודה")

    # יוצר טבלה אם לא קיימת
    import sqlite3
    from pathlib import Path
    DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "project_control.sqlite"

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS site_journal (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      TEXT NOT NULL,
            date            TEXT,
            month           TEXT,
            site_manager    TEXT,
            description     TEXT,
            notes           TEXT,
            created_at      TEXT,
            updated_at      TEXT
        )""")

    project_id = project_meta["project_id"]
    with sqlite3.connect(DB_PATH) as conn:
        rows = pd.read_sql(
            "SELECT * FROM site_journal WHERE project_id = ? ORDER BY date DESC, id DESC",
            conn, params=[project_id],
        )

    show_cols = ["id", "date", "site_manager", "description", "notes"]
    rows = rows[show_cols] if not rows.empty else pd.DataFrame(columns=show_cols)
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce") if not rows.empty else rows.get("date")

    original_ids = set(rows["id"].dropna().astype(int).tolist()) if not rows.empty else set()

    edited = st.data_editor(
        rows,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "date": st.column_config.DateColumn("תאריך *", required=True, format="DD/MM/YYYY"),
            "site_manager": st.column_config.TextColumn("מנהל עבודה"),
            "description": st.column_config.TextColumn("תיאור עבודה יומי *", required=True),
            "notes": st.column_config.TextColumn("הערות"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"site_journal_{project_id}",
    )

    if st.button("💾 שמור יומן אתר", type="primary", key=f"save_journal_{project_id}"):
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        inserted = updated = deleted = 0
        current_ids = set()
        with sqlite3.connect(DB_PATH) as conn:
            for _, r in edited.iterrows():
                rid = r.get("id")
                d = pd.to_datetime(r.get("date"), errors="coerce")
                date_str = d.strftime("%Y-%m-%d") if pd.notna(d) else None
                month_str = d.strftime("%m-%Y") if pd.notna(d) else None
                desc = str(r.get("description", "") or "").strip()
                if not date_str or not desc:
                    continue
                if pd.isna(rid):
                    conn.execute(
                        """INSERT INTO site_journal (project_id, date, month, site_manager,
                           description, notes, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        [project_id, date_str, month_str,
                         str(r.get("site_manager", "") or ""),
                         desc, str(r.get("notes", "") or ""), now, now],
                    )
                    inserted += 1
                else:
                    current_ids.add(int(rid))
                    conn.execute(
                        """UPDATE site_journal SET date=?, month=?, site_manager=?,
                           description=?, notes=?, updated_at=? WHERE id=?""",
                        [date_str, month_str, str(r.get("site_manager", "") or ""),
                         desc, str(r.get("notes", "") or ""), now, int(rid)],
                    )
                    updated += 1
            removed = original_ids - current_ids
            for rid in removed:
                conn.execute("DELETE FROM site_journal WHERE id = ?", [rid])
                deleted += 1
        st.success(f"נשמר: +{inserted} ~{updated} -{deleted}")
        st.rerun()


# ─── תפעול ושטח → שעות עבודה כלים ───────────────────────────
def _subtab_equipment_hours(df: pd.DataFrame, project_meta: dict) -> None:
    """שעות עבודה כלים - מאחד hours.xlsx + site_tracking + control_db."""
    sec("שעות עבודה כלים", meta="מאוחד מ-hours.xlsx + site_tracking + הזנה ידנית")
    project_id = project_meta["project_id"]

    hours_master = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    from pipeline import load_site_tracking_data
    site_data = load_site_tracking_data(project_id)
    site_hours = site_data.get("tools_hours", pd.DataFrame())
    from core import control_db
    manual = control_db.list_rows("equipment_work_logs", project_id)

    sources = []
    if not hours_master.empty:
        sources.append(("hours.xlsx", len(hours_master), float(hours_master["work_hours"].sum())))
    if not site_hours.empty and "work_hours" in site_hours.columns:
        sources.append(("site_tracking", len(site_hours), float(site_hours["work_hours"].sum())))
    if not manual.empty and "work_hours" in manual.columns:
        sources.append(("הזנה ידנית", len(manual), float(manual["work_hours"].sum())))

    if not sources:
        ins("blue", "ℹ️", "אין נתוני שעות עבודה כלים",
            "טען <code>hours.xlsx</code> או הוסף שעות בטאב 'יומני שטח'.")
        return

    cols_kpi = st.columns(len(sources) + 1)
    cols_kpi[0].metric("מקורות נתונים", str(len(sources)))
    for i, (src, n, h) in enumerate(sources):
        cols_kpi[i + 1].metric(f"{src}", f"{h:,.0f} ש'", help=f"{n} שורות")

    if not site_hours.empty:
        sec("מ-site_tracking")
        cols = [c for c in ["date", "tool_name", "license_num", "start_time",
                            "end_time", "work_hours", "section", "notes"]
                if c in site_hours.columns]
        heb = {"date": "תאריך", "tool_name": "כלי", "license_num": "רישוי",
               "start_time": "התחלה", "end_time": "סיום", "work_hours": "שעות",
               "section": "סעיף", "notes": "הערות"}
        disp = site_hours[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        st.dataframe(disp.head(200), use_container_width=True, hide_index=True)
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
        st.dataframe(disp, use_container_width=True, hide_index=True)


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
            "טען site_tracking או הוסף שעות בטאב 'יומני שטח'.")
        return

    if not sub_hours.empty:
        per = sub_hours.groupby("name").agg(
            days=("date", "nunique"),
            hours=("work_hours", "sum"),
        ).reset_index().sort_values("hours", ascending=False).round(1)
        per.columns = ["שם קבלן/משאית", "ימי עבודה", "סה\"כ שעות"]
        st.dataframe(per, use_container_width=True, hide_index=True)

        with st.expander("פירוט יומי"):
            cols = [c for c in ["date", "name", "license_num", "start_time",
                                "end_time", "work_hours", "notes"] if c in sub_hours.columns]
            heb = {"date": "תאריך", "name": "שם", "license_num": "מס' רכב",
                   "start_time": "התחלה", "end_time": "סיום",
                   "work_hours": "שעות", "notes": "הערות"}
            disp = sub_hours[cols].sort_values("date" if "date" in cols else cols[0])
            disp.columns = [heb.get(c, c) for c in cols]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    if not manual.empty:
        sec("הזנות ידניות")
        cols = [c for c in ["date", "contractor_name", "work_type", "quantity",
                            "hours", "days", "price", "invoice_num"] if c in manual.columns]
        heb = {"date": "תאריך", "contractor_name": "שם קבלן", "work_type": "סוג עבודה",
               "quantity": "כמות", "hours": "שעות", "days": "ימים",
               "price": "מחיר", "invoice_num": "חשבונית"}
        disp = manual[cols].sort_values("date" if "date" in cols else cols[0])
        disp.columns = [heb.get(c, c) for c in cols]
        st.dataframe(disp, use_container_width=True, hide_index=True)


# ─── סולר וכלים → קניות סולר ───────────────────────────────
def _subtab_fuel_purchases(df: pd.DataFrame, project_meta: dict) -> None:
    """קניות סולר - הפרדה לפי סוג דלק (סולר צמ"ה/רכבים/בנזין/חשמל) + מקורות שונים."""
    from pipeline import load_fuel_invoices_data
    from core.fuel_invoices_loader import summary_by_supplier, summary_by_month

    # ── ראש: 5 כרטיסים לפי סוג דלק ──
    sec("פילוח דלק ואנרגיה לפי סוג", meta="מבוסס על account_type + description")
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
                            st.dataframe(sup.sort_values("סה\"כ (₪)", ascending=False),
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
                    st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── דלק לפי כלי - שילוב מקורות + matching ל-equipment ──
    sec("דלק לפי כלי", meta="חיבור אוטומטי ל-tools_registry")
    from core.equipment_matcher import enrich_fuel_transactions
    from pipeline import _load_tools_registry, load_fuel_invoices_data
    equipment = _load_tools_registry()
    if equipment.empty:
        st.caption("אין כלים ב-tools_registry — לא ניתן להתאים.")
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

            # ── סטטיסטיקת matching ──
            n_total = len(enriched)
            n_matched = int((enriched["matched_by"] != "unmatched").sum())
            n_high = int((enriched["match_confidence"] == "high").sum())
            n_low = int((enriched["match_confidence"] == "low").sum())
            n_err = int((enriched["validation_status"] == "error").sum())
            n_warn = int((enriched["validation_status"] == "warning").sum())
            mk1, mk2, mk3, mk4, mk5 = st.columns(5)
            mk1.metric("סה\"כ תנועות דלק", str(n_total))
            mk2.metric("הותאמו לכלי", str(n_matched),
                         delta=f"{(n_matched/n_total*100):.0f}%" if n_total else None)
            mk3.metric("בטחון גבוה", str(n_high))
            mk4.metric("אזהרות validation", str(n_warn))
            mk5.metric("שגיאות validation", str(n_err))

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
                st.dataframe(disp.sort_values("סה\"כ ₪", ascending=False),
                             use_container_width=True, hide_index=True)
            else:
                st.caption("אף תנועת דלק לא הצליחה להתאים לכלי.")

            # ── תנועות לא מותאמות ──
            unmatched = enriched[enriched["matched_by"] == "unmatched"]
            if not unmatched.empty:
                sec(f"דלק ללא כלי מזוהה ({len(unmatched)} תנועות)",
                    meta="דורש הוספת הכלי ל-tools_registry או בחירה ידנית")
                cols = [c for c in ["date", "month", "source_kind", "supplier",
                                      "description", "qty_liters", "total_cost",
                                      "fuel_type", "match_note"]
                        if c in unmatched.columns]
                heb = {"date": "תאריך", "month": "חודש", "source_kind": "מקור",
                       "supplier": "ספק", "description": "פרטים",
                       "qty_liters": "ליטרים", "total_cost": "₪", "fuel_type": "סוג דלק",
                       "match_note": "הערת התאמה"}
                disp_u = unmatched[cols].copy()
                for c in ("qty_liters", "total_cost"):
                    if c in disp_u.columns:
                        disp_u[c] = pd.to_numeric(disp_u[c], errors="coerce").round(0)
                disp_u.columns = [heb.get(c, c) for c in cols]
                st.dataframe(disp_u, use_container_width=True, hide_index=True)

                # ייצוא חריגות
                from io import BytesIO
                buf = BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    disp_u.to_excel(writer, sheet_name="לא מותאמים", index=False)
                st.download_button(
                    f"⬇️ ייצוא {len(unmatched)} תנועות לא מותאמות לאקסל",
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
                st.dataframe(disp_e, use_container_width=True, hide_index=True)

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
                        st.dataframe(disp_t.sort_values("תאריך" if "תאריך" in disp_t.columns else disp_t.columns[0]),
                                     use_container_width=True, hide_index=True)

    # ── מקור 2 (לשעבר היה ראשי): דוח רכש פריטים - חשבונית-לחשבונית ──
    sec("חשבוניות סולר ברמת פירוט", meta="מ-fuel_invoices.xlsx (דוח רכש פריטים)")
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
        c2.metric("ליטרים", f"{total_l:,.0f}")
        c3.metric("סה\"כ עלות", f"₪{total_c:,.0f}")
        c4.metric("₪ ממוצע לליטר", f"{avg_p:.2f}")

        # ─ סיכום לפי ספק ─
        with st.expander("לפי ספק", expanded=True):
            sup = summary_by_supplier(inv)
            sup.columns = ["ספק", "חשבוניות", "ליטרים", "סה\"כ (₪)", "₪/ל'"]
            st.dataframe(sup, use_container_width=True, hide_index=True)

        # ─ סיכום חודשי + זיהוי קפיצות מחיר ─
        with st.expander("לפי חודש (₪/ליטר) - לזיהוי קפיצות מחיר", expanded=True):
            mo = summary_by_month(inv)
            mo.columns = ["חודש", "חשבוניות", "ליטרים", "סה\"כ (₪)", "₪/ל'"]
            st.dataframe(mo, use_container_width=True, hide_index=True)
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
            st.dataframe(disp.sort_values("תאריך", ascending=False),
                         use_container_width=True, hide_index=True)

    # ── מקור 2: חשבשבת כרטיס (חשבונות סולר) ──
    sec("חיובי סולר מכרטיס ההנהלה", meta="cross-check עם דוח הרכש")
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
    c1.metric("מחשבשבת (₪)", f"₪{total_chash:,.0f}")
    c2.metric("מהזנה ידנית (ל')", f"{total_manual_liters:,.0f}")
    c3.metric("מהזנה ידנית (₪)", f"₪{total_manual_cost:,.0f}")

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
        st.dataframe(disp, use_container_width=True, hide_index=True)

        # קבץ לפי ספק
        with st.expander("חלוקה לפי ספק"):
            by_sup = fuel_chash.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
            by_sup.columns = ["ספק", "סה\"כ (₪)", "חשבוניות"]
            by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
            st.dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
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
        st.dataframe(disp, use_container_width=True, hide_index=True)


# ─── סולר וכלים → שימוש בסולר ──────────────────────────────
def _subtab_fuel_usage(df: pd.DataFrame, project_meta: dict) -> None:
    """שימוש בסולר בפועל - מ-solar.xlsx ומ-site_tracking.fuel."""
    sec("שימוש בסולר", meta="תדלוקים בפועל לכלים")
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    from pipeline import load_site_tracking_data
    site_fuel = load_site_tracking_data(project_meta["project_id"]).get("fuel", pd.DataFrame())

    total_solar_l = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0
    total_site_l = float(site_fuel["liters"].sum()) if "liters" in site_fuel.columns and not site_fuel.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("מ-solar.xlsx (ל')", f"{total_solar_l:,.0f}")
    c2.metric("מ-site_tracking (ל')", f"{total_site_l:,.0f}")
    c3.metric("סה\"כ", f"{total_solar_l + total_site_l:,.0f}")

    if not solar.empty:
        sec("תדלוקים מ-solar.xlsx (Pointer/דלקן)")
        cols = [c for c in ["date", "tool_name", "license_num", "liters", "engine_hours"]
                if c in solar.columns]
        st.dataframe(solar[cols].sort_values("date" if "date" in cols else cols[0]),
                     use_container_width=True, hide_index=True)

    if not site_fuel.empty:
        sec("תדלוקים מ-site_tracking")
        cols = [c for c in ["date", "tool_name", "license_num", "liters",
                            "engine_hours", "lph_actual", "notes"]
                if c in site_fuel.columns]
        st.dataframe(site_fuel[cols].sort_values("date" if "date" in cols else cols[0]),
                     use_container_width=True, hide_index=True)


# ─── סולר וכלים → מלאי סולר ────────────────────────────────
def _subtab_fuel_inventory(df: pd.DataFrame, project_meta: dict) -> None:
    """מאזן מלאי סולר - פתיחה + קניות - שימושים = סגירה."""
    sec("מאזן מלאי סולר", meta="מ-fuel_inventory.xlsx (אופציונלי, ידני)")
    project_id = project_meta["project_id"]
    inv = _collect_fuel_inventory(project_id)
    if inv.empty:
        ins("blue", "ℹ️", "אין קובץ fuel_inventory.xlsx",
            "הוסף קובץ עם עמודות <code>חודש / מלאי פתיחה (ל') / מלאי סגירה (ל')</code> "
            "לתיקיית החודש כדי לראות מאזן מלאי.")
        return

    # Compute purchases and usage per month
    fuel_chash = _filter_by_keywords(df, KEYWORD_CATEGORIES["fuel"])
    if "amount" in fuel_chash.columns:
        fuel_chash = fuel_chash[fuel_chash["amount"] > 0]
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    total_chash = float(fuel_chash["amount"].sum()) if not fuel_chash.empty else 0
    total_solar_l = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0
    avg_price = total_chash / total_solar_l if total_solar_l > 0 else 0

    pp = {}
    if not fuel_chash.empty and avg_price > 0 and "month" in fuel_chash.columns:
        for m, grp in fuel_chash.groupby("month"):
            pp[m] = float(grp["amount"].sum()) / avg_price
    upm = {}
    if not solar.empty and "month" in solar.columns:
        for m, grp in solar.groupby("month"):
            upm[m] = float(grp["liters"].sum())

    from core.fuel_inventory import compute_balance
    balance = compute_balance(inv, pp, upm)
    if balance.empty:
        st.caption("אין מספיק נתונים לחישוב מאזן.")
        return

    disp = balance.copy()
    disp.columns = ["חודש", "פתיחה", "קניות", "שימושים", "סגירה צפויה",
                    "סגירה בפועל", "הפרש", "סטטוס"]
    st.dataframe(disp, use_container_width=True, hide_index=True)
    n_bad = int((balance["status"] == "חוסר").sum())
    if n_bad:
        ins("amber", "⚠️", f"{n_bad} חודשים עם חוסר",
            "ההפרש מצביע על שימוש לא מתועד או פחת חריג.")


# ─── סולר וכלים → צריכת סולר לפי כלי ───────────────────────
def _subtab_consumption_per_tool(df: pd.DataFrame, project_meta: dict) -> None:
    """ל'/ש' בפועל לכל כלי, מול תקן עליון."""
    sec("צריכת סולר לפי כלי", meta="ל'/ש' מול תקן עליון × 1.15")
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    if solar.empty or hours.empty:
        ins("blue", "ℹ️", "נדרשים גם solar.xlsx וגם hours.xlsx", "")
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
        st.dataframe(disp, use_container_width=True, hide_index=True)


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
        st.metric("סה\"כ אחזקה (₪)", f"₪{float(maint['amount'].sum()):,.0f}")
        by_sup = maint.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_sup.columns = ["ספק / מוסך", "סה\"כ (₪)", "תנועות"]
        by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
        st.dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
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
        st.dataframe(disp, use_container_width=True, hide_index=True)

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
        st.dataframe(disp, use_container_width=True, hide_index=True)


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
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.caption("עלות אחזקה מחולקת באופן יחסי לשעות העבודה - מודל פשוט. "
               "לדיוק מלא, נדרש שדה license_num בכל חשבונית אחזקה.")


# ─── ייבוא ועדכון → היסטוריית ייבוא ────────────────────────
def _subtab_import_history(project_meta: dict) -> None:
    """רשימת קבצים שיובאו - מ-storage.imported_files (SQLite) + יכולת מחיקת חודש."""
    from core import storage
    project_id = project_meta["project_id"]

    sec("היסטוריית ייבוא", meta="מ-imported_files (SQLite)")
    files = storage.list_imported_files(project_id)
    if files.empty:
        ins("blue", "ℹ️", "אין רישומי ייבוא ב-SQLite",
            "הרץ <code>python -c \"from pipeline import build_master; build_master()\"</code> "
            "כדי לרשום את הקבצים הקיימים.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("קבצים", str(len(files)))
        c2.metric("חודשים", str(files["month"].nunique()))
        c3.metric("סה\"כ שורות נטענו", f"{files['rows_loaded'].sum():,}")
        c4.metric("שגיאות", str(int(files["error_count"].sum())))

        cols = ["imported_at", "month", "file_type", "file_name", "rows_loaded",
                "file_size_kb", "status", "imported_by"]
        cols = [c for c in cols if c in files.columns]
        disp = files[cols].copy()
        heb = {"imported_at": "תאריך ייבוא", "month": "חודש", "file_type": "סוג",
               "file_name": "שם קובץ", "rows_loaded": "שורות נטענו",
               "file_size_kb": "גודל KB", "status": "סטטוס", "imported_by": "משתמש"}
        disp.columns = [heb.get(c, c) for c in cols]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── מחיקת חודש מלא מהמערכת ──
    sec("מחיקת חודש מהמערכת", meta="מסיר רשומות מ-SQLite (אופציונלית גם קבצים)")
    months = sorted(files["month"].dropna().unique().tolist()) if not files.empty else []
    if not months:
        from pipeline import list_available_months
        months = list_available_months(project_id)

    col_m, col_b, col_files = st.columns([2, 1, 2])
    with col_m:
        del_month = st.selectbox("חודש למחיקה", [""] + months, key="del_month_sel")
    with col_files:
        delete_files = st.checkbox("מחק גם את קבצי ה-xlsx", key="del_files_chk", value=False)
    with col_b:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        confirm_key = f"del_confirm_{project_id}_{del_month}"
        if not st.session_state.get(confirm_key):
            if st.button("⚠️ הכן מחיקה",
                          disabled=not del_month, key="del_prep",
                          type="secondary", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            if st.button("🗑 אשר מחיקה", key="del_confirm",
                          type="primary", use_container_width=True):
                result = storage.delete_project_month(
                    project_id, del_month, delete_files=delete_files,
                )
                st.success(f"נמחק: {result}")
                st.session_state.pop(confirm_key, None)
                st.cache_data.clear()
                st.rerun()
    if del_month and st.session_state.get(confirm_key):
        st.warning(f"⚠️ עומד למחוק את כל נתוני {project_id} / {del_month}. "
                   f"לחץ 'אשר מחיקה' להמשך, או refresh לביטול.")


# ─── ייבוא ועדכון → גיבוי וייצוא ───────────────────────────
def _subtab_backup_export(project_meta: dict) -> None:
    """גיבוי SQLite + ייצוא נתוני פרויקט לאקסל."""
    from io import BytesIO
    from datetime import datetime
    from pathlib import Path
    from core import storage
    project_id = project_meta["project_id"]

    sec("גיבוי בסיסי הנתונים", meta="data/backups/")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("📥 צור גיבוי מלא עכשיו", key="run_backup",
                       type="primary", use_container_width=True):
            backups = storage.backup_database()
            st.success(f"נוצרו {len(backups)} קובצי גיבוי ב-data/backups/")
            for name, path in backups.items():
                st.caption(f"  • {name} → {path.name}")
            st.rerun()
    with c2:
        # Direct download of current SQLite
        if storage.DB_CONTROL.exists():
            with open(storage.DB_CONTROL, "rb") as f:
                data = f.read()
            st.download_button(
                f"⬇️ הורד SQLite נוכחי ({len(data) // 1024} KB)",
                data=data,
                file_name=f"project_control_{datetime.now().strftime('%Y%m%d_%H%M')}.sqlite",
                mime="application/x-sqlite3",
                use_container_width=True,
            )

    # רשימת גיבויים שמורים
    backups_list = storage.list_backups()
    if not backups_list.empty:
        with st.expander(f"היסטוריית גיבויים ({len(backups_list)})"):
            disp = backups_list.copy()
            disp.columns = ["שם קובץ", "גודל (KB)", "תאריך"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    sec("ייצוא נתוני פרויקט לאקסל")
    if st.button("📊 צור קובץ Excel עם כל נתוני הפרויקט", key="export_xlsx"):
        from pipeline import load_master, load_site_tracking_data
        from core import control_db, budget_db

        with st.spinner("בונה קובץ Excel..."):
            master = load_master()
            project_master = master[master["project_id"] == project_id] if not master.empty else master
            site_data = load_site_tracking_data(project_id)

            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                if not project_master.empty:
                    project_master.to_excel(writer, sheet_name="transactions", index=False)
                for sheet_key, sd in site_data.items():
                    if not sd.empty and len(sd) > 0:
                        sd.to_excel(writer, sheet_name=f"site_{sheet_key}"[:31], index=False)
                # control_db tables
                for table in ["fuel_logs", "equipment_work_logs", "employee_work_logs",
                              "contractor_work_logs", "maintenance_logs"]:
                    rows = control_db.list_rows(table, project_id)
                    if not rows.empty:
                        rows.to_excel(writer, sheet_name=table[:31], index=False)
                # budget
                budget = budget_db.get_budget(project_id)
                if not budget.empty:
                    budget.to_excel(writer, sheet_name="budget", index=False)

            data = buf.getvalue()
        st.success(f"קובץ נוצר: {len(data) // 1024} KB")
        st.download_button(
            f"⬇️ הורד export_{project_id}.xlsx",
            data=data,
            file_name=f"export_{project_id}_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


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
    }.get(key, key)
