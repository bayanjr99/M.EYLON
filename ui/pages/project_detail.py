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
    status = project_meta.get("status", "active")

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

    # ── 8 טאבים ראשיים מאורגנים לפי תחומים ─────────────────
    tabs = st.tabs([
        "📊 סקירה כללית",
        "💰 כספים",
        "🏗️ תפעול ושטח",
        "⛽ סולר וכלים",
        "🏢 ספקים וקבלנים",
        "📈 תקציב מול ביצוע",
        "🔍 בדיקות וחריגות",
        "📁 ייבוא ועדכון נתונים",
    ])

    with tabs[0]:
        _tab_overview(df, summary)

    with tabs[1]:
        # כספים: 5 sub-tabs
        sub = st.tabs(["הכנסות", "הוצאות", "פירוט תנועות",
                        "חשבונות חשבשבת", "גבייה"])
        with sub[0]:
            _tab_income(df)
        with sub[1]:
            _tab_expenses(df)
        with sub[2]:
            _tab_transactions(df)
        with sub[3]:
            _subtab_accounts_rollup(df)
        with sub[4]:
            _subtab_collection_status(df)

    with tabs[2]:
        # תפעול ושטח: 4 sub-tabs
        sub = st.tabs(["יומן אתר", "שעות עבודה כלים", "עובדים", "קבלני משנה בשטח"])
        with sub[0]:
            _subtab_site_journal(project_meta)
        with sub[1]:
            _subtab_equipment_hours(df, project_meta)
        with sub[2]:
            _tab_employees(df, project_meta)
        with sub[3]:
            _subtab_contractors_field(df, project_meta)

    with tabs[3]:
        # סולר וכלים: 6 sub-tabs
        sub = st.tabs(["קניות סולר", "שימוש בסולר", "מלאי סולר",
                        "צריכת סולר לפי כלי", "טיפולים ואחזקה", "עלות כלי לשעה"])
        with sub[0]:
            _subtab_fuel_purchases(df, project_meta)
        with sub[1]:
            _subtab_fuel_usage(df, project_meta)
        with sub[2]:
            _subtab_fuel_inventory(df, project_meta)
        with sub[3]:
            _subtab_consumption_per_tool(df, project_meta)
        with sub[4]:
            _subtab_maintenance(df, project_meta)
        with sub[5]:
            _subtab_cost_per_hour(df, project_meta)

    with tabs[4]:
        # ספקים וקבלנים (היחיד שלא צריך sub-tabs עמוקים, יש פנים פילטרים)
        _tab_suppliers(df, project_meta)

    with tabs[5]:
        # תקציב מול ביצוע - הטאב החדש
        from ui.pages.budget import render_budget_tab
        render_budget_tab(df, project_meta)

    with tabs[6]:
        # בדיקות וחריגות
        _tab_qa(df, project_meta)

    with tabs[7]:
        # ייבוא ועדכון נתונים: 4 sub-tabs
        sub = st.tabs(["ייבוא קבצים", "יומני שטח (הזנה ידנית)",
                        "היסטוריית ייבוא", "גיבוי וייצוא"])
        with sub[0]:
            from ui.pages.import_data import render_import_page
            from pipeline import list_available_projects
            render_import_page(list_available_projects())
        with sub[1]:
            from ui.pages.field_data_entry import render_field_data_entry
            render_field_data_entry(project_meta)
        with sub[2]:
            _subtab_import_history(project_meta)
        with sub[3]:
            _subtab_backup_export(project_meta)


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

    sec("מגמה חודשית")
    trend = analytics.monthly_trend(df)
    if trend.empty:
        st.caption("אין מספיק חודשים להצגת מגמה.")
    else:
        disp = trend.copy()
        disp.columns = ["חודש", "הוצאות", "הכנסות", "יתרה"]
        st.dataframe(disp.round(0), use_container_width=True, hide_index=True)


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
    # הכנסות = amount שלילי (חשבונות 927/951/7367 נורמלו לסלילי) או מילות מפתח
    income = df[df["amount"] < 0] if "amount" in df.columns else df.iloc[0:0]
    income_kw = _filter_by_keywords(df, KEYWORD_CATEGORIES["income"])
    income_all = (pd.concat([income, income_kw]).drop_duplicates()
                  if not income_kw.empty else income)

    if income_all.empty:
        ins("blue", "ℹ️", "אין הכנסות מתועדות",
            "הכנסות מזוהות לפי חשבונות {927, 951, 7367} או מילות מפתח כמו "
            "'הכנסות', 'חיוב ספק'. ודא שהמאזן/כרטיס ההנהלה כולל אותם.")
        return

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


# ─── Tab 5: ספקים וקבלנים (עם site_tracking) ────────────────
def _tab_suppliers(df: pd.DataFrame, project_meta: dict | None = None) -> None:
    from pipeline import load_site_tracking_data
    project_id = df["project_id"].iloc[0] if not df.empty and "project_id" in df.columns else None

    sec("Top 30 ספקים בפרויקט")
    sup = project_aggregator.by_supplier(df, top_n=30)
    if sup.empty:
        ins("blue", "ℹ️", "אין ספקים מתועדים", "ספקים מחולצים מ-'פרטים' בכרטיס ההנהלה.")
    else:
        disp = sup.copy()
        disp["total_amount"] = disp["total_amount"].round(0)
        disp.columns = ["ספק", "סה\"כ (₪)", "תנועות", "פרויקטים", "מתאריך", "עד תאריך"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

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
    from core import categorizer
    from pipeline import list_available_months, PROJECTS_ROOT

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
        from io import BytesIO
        buf = BytesIO()
        unmapped.to_excel(buf, index=False, engine="openpyxl")
        st.download_button("⬇️ הורד unmapped_accounts.xlsx",
                           data=buf.getvalue(),
                           file_name="unmapped_accounts.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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


# ════════════════════════════════════════════════════════════
# SUB-TABS חדשים למבנה המקצועי (8 ראשיים)
# ════════════════════════════════════════════════════════════

# ─── כספים → חשבונות חשבשבת ─────────────────────────────────
def _subtab_accounts_rollup(df: pd.DataFrame) -> None:
    """ריכוז לפי חשבון: חובה / זכות / יתרה / קטגוריה / האם ממופה."""
    sec("ריכוז חשבונות חשבשבת")
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
    if chash.empty:
        ins("blue", "ℹ️", "אין נתוני חשבשבת", "טען כרטיס הנהלה.")
        return

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
    """קניות סולר מחשבשבת + הזנות ידניות (fuel_logs)."""
    sec("קניות סולר", meta="מחשבשבת + הזנה ידנית")
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
    """רשימת קבצים שיובאו: סריקת תיקיות הפרויקט."""
    sec("היסטוריית ייבוא", meta="סריקת data/projects/<id>/")
    from pipeline import PROJECTS_ROOT
    from datetime import datetime
    project_id = project_meta["project_id"]
    project_dir = PROJECTS_ROOT / project_id
    if not project_dir.exists():
        st.caption("תיקיית פרויקט לא קיימת.")
        return

    rows = []
    for month_dir in sorted(project_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        for f in month_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
                continue
            if f.name.startswith("~$"):
                continue
            stat = f.stat()
            rows.append({
                "חודש": month_dir.name,
                "שם קובץ": f.name,
                "גודל (KB)": stat.st_size // 1024,
                "תאריך עדכון": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
            })
    # Project-wide files
    for f in project_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
            continue
        if f.name.startswith("~$"):
            continue
        stat = f.stat()
        rows.append({
            "חודש": "—",
            "שם קובץ": f.name,
            "גודל (KB)": stat.st_size // 1024,
            "תאריך עדכון": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        })

    if not rows:
        st.caption("לא נמצאו קבצים בתיקיית הפרויקט.")
    else:
        df_h = pd.DataFrame(rows)
        st.dataframe(df_h, use_container_width=True, hide_index=True)
        st.caption(f"{len(df_h)} קבצים בסה\"כ.")


# ─── ייבוא ועדכון → גיבוי וייצוא ───────────────────────────
def _subtab_backup_export(project_meta: dict) -> None:
    """גיבוי SQLite + ייצוא נתוני פרויקט לאקסל."""
    from io import BytesIO
    from datetime import datetime
    from pathlib import Path
    project_id = project_meta["project_id"]

    sec("גיבוי בסיסי הנתונים")
    DB_CONTROL = Path(__file__).resolve().parent.parent.parent / "data" / "project_control.sqlite"
    if DB_CONTROL.exists():
        with open(DB_CONTROL, "rb") as f:
            data = f.read()
        st.download_button(
            f"⬇️ הורד גיבוי project_control.sqlite ({len(data) // 1024} KB)",
            data=data,
            file_name=f"project_control_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.sqlite",
            mime="application/x-sqlite3",
        )
    else:
        st.caption("project_control.sqlite לא קיים עדיין.")

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
