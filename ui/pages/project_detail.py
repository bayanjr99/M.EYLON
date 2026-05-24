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
        empty_state(
            icon="ti-database-off",
            title=f"אין עדיין נתונים לפרויקט {project_name}",
            body_html=(
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

    tabs = st.tabs([
        "📊 סקירה כללית",
        "💰 הכנסות",
        "💸 הוצאות",
        "👷 עובדים ושכר",
        "🏢 ספקים וקבלנים",
        "⛽ סולר ואחזקה",
        "🚜 רכבים וכלים",
        "📋 פירוט תנועות",
        "🤖 AI / חריגות",
    ])

    with tabs[0]:
        _tab_overview(df, summary)
    with tabs[1]:
        _tab_income(df)
    with tabs[2]:
        _tab_expenses(df)
    with tabs[3]:
        _tab_employees(df)
    with tabs[4]:
        _tab_suppliers(df)
    with tabs[5]:
        _tab_fuel_maintenance(df)
    with tabs[6]:
        _tab_vehicles_tools(df)
    with tabs[7]:
        _tab_transactions(df)
    with tabs[8]:
        _tab_ai_anomalies(df, project_id)


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


# ─── Tab 2: הכנסות ──────────────────────────────────────────
def _tab_income(df: pd.DataFrame) -> None:
    sec("הכנסות הפרויקט")
    income = df[df["amount"] < 0] if "amount" in df.columns else df.iloc[0:0]
    income_kw = _filter_by_keywords(df, KEYWORD_CATEGORIES["income"])
    income_all = pd.concat([income, income_kw]).drop_duplicates() if not income_kw.empty else income

    if income_all.empty:
        ins("blue", "ℹ️", "אין הכנסות מתועדות",
            "הכנסות מזוהות לפי חשבונות {927, 951, 7367} או מילות מפתח כמו "
            "'הכנסות', 'חיוב ספק'. ודא שהמאזן/כרטיס ההנהלה כולל אותם.")
        return

    total = float(-income_all.loc[income_all["amount"] < 0, "amount"].sum()
                  + income_all.loc[income_all["amount"] > 0, "amount"].sum())
    st.metric("סה\"כ הכנסות", _fmt_money(total))

    sec("הכנסות לפי חודש")
    if "month" in income_all.columns:
        monthly = income_all.groupby("month")["amount"].sum().abs().reset_index()
        monthly.columns = ["חודש", "סכום"]
        st.dataframe(monthly.round(0), use_container_width=True, hide_index=True)

    sec("פירוט")
    cols_show = [c for c in ["date", "account_name", "supplier", "description", "amount"]
                 if c in income_all.columns]
    st.dataframe(income_all[cols_show], use_container_width=True, hide_index=True)


# ─── Tab 3: הוצאות ──────────────────────────────────────────
def _tab_expenses(df: pd.DataFrame) -> None:
    sec("הוצאות לפי קטגוריה")
    cat = project_aggregator.by_category(df)
    if cat.empty:
        ins("blue", "ℹ️", "אין הוצאות מתועדות", "טען קובץ chashbashevet.xlsx לחודש.")
        return

    disp = cat.copy()
    disp["total_amount"] = disp["total_amount"].round(0)
    disp.columns = ["קטגוריה", "סכום", "תנועות", "% מסך"]
    st.dataframe(disp, use_container_width=True, hide_index=True)

    sec("חלוקה לפי תת-קטגוריות")
    breakdown = {}
    for label, keywords in KEYWORD_CATEGORIES.items():
        if label == "income":
            continue
        sub = _filter_by_keywords(df, keywords)
        sub = sub[sub["amount"] > 0] if "amount" in sub.columns else sub
        if not sub.empty:
            breakdown[label] = float(sub["amount"].sum())

    if breakdown:
        rows = [{"קטגוריה": _label_he(k), "סה\"כ (₪)": round(v, 0)}
                for k, v in sorted(breakdown.items(), key=lambda x: -x[1])]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ─── Tab 4: עובדים ושכר ─────────────────────────────────────
def _tab_employees(df: pd.DataFrame) -> None:
    salary_df = _filter_by_keywords(df, KEYWORD_CATEGORIES["salary"])
    if "amount" in salary_df.columns:
        salary_df = salary_df[salary_df["amount"] > 0]

    if salary_df.empty:
        ins("amber", "⚠️", "אין נתוני שכר לפרויקט זה",
            "כרטיס ההנהלה לא כולל חשבונות עם מילים: שכר, עובדים, ביטוח לאומי, גמל וכו'.")
        return

    total_salary = float(salary_df["amount"].sum()) if "amount" in salary_df.columns else 0
    st.metric("סה\"כ עלות שכר בפרויקט", _fmt_money(total_salary))

    sec("חלוקה לפי חשבון שכר")
    if "account_name" in salary_df.columns:
        by_acct = salary_df.groupby("account_name")["amount"].agg(["sum", "count"]).reset_index()
        by_acct.columns = ["חשבון", "סכום", "תנועות"]
        by_acct["סכום"] = by_acct["סכום"].round(0)
        st.dataframe(by_acct.sort_values("סכום", ascending=False),
                     use_container_width=True, hide_index=True)

    sec("שכר לפי חודש")
    if "month" in salary_df.columns:
        monthly = salary_df.groupby("month")["amount"].sum().reset_index()
        monthly.columns = ["חודש", "עלות שכר"]
        st.dataframe(monthly.round(0), use_container_width=True, hide_index=True)

    ins("blue", "ℹ️", "פירוט ברמת עובד בודד",
        "המאזן/כרטיס ההנהלה מספק סיכומים ברמת חשבון. לפירוט שעות+עלות לכל עובד "
        "נדרש דוח שכר ייעודי - יתווסף בעתיד.")


# ─── Tab 5: ספקים וקבלנים ───────────────────────────────────
def _tab_suppliers(df: pd.DataFrame) -> None:
    sec("Top 30 ספקים בפרויקט")
    sup = project_aggregator.by_supplier(df, top_n=30)
    if sup.empty:
        ins("blue", "ℹ️", "אין ספקים מתועדים", "ספקים מחולצים מ-'פרטים' בכרטיס ההנהלה.")
        return
    disp = sup.copy()
    disp["total_amount"] = disp["total_amount"].round(0)
    disp.columns = ["ספק", "סה\"כ (₪)", "תנועות", "פרויקטים", "מתאריך", "עד תאריך"]
    st.dataframe(disp, use_container_width=True, hide_index=True)

    sec("קבלני משנה בלבד")
    subs = _filter_by_keywords(df, KEYWORD_CATEGORIES["subcontractors"])
    if subs.empty:
        st.caption("לא זוהו תנועות תחת 'קבלני משנה'.")
    else:
        cols = [c for c in ["date", "supplier", "description", "amount"] if c in subs.columns]
        st.dataframe(subs[cols], use_container_width=True, hide_index=True)


# ─── Tab 6: סולר ואחזקה ─────────────────────────────────────
def _tab_fuel_maintenance(df: pd.DataFrame) -> None:
    sec("תדלוקים")
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    if solar.empty:
        ins("blue", "ℹ️", "אין נתוני תדלוק", "טען <code>solar.xlsx</code> לחודש.")
    else:
        total_l = float(solar["liters"].sum()) if "liters" in solar.columns else 0
        st.metric("סה\"כ ליטרים", f"{total_l:,.0f}")
        cols = [c for c in ["date", "tool_name", "license_num", "liters", "engine_hours"]
                if c in solar.columns]
        st.dataframe(solar[cols], use_container_width=True, hide_index=True)

    sec("אחזקות (מוסך, תיקונים, חלפים)")
    maint = _filter_by_keywords(df, KEYWORD_CATEGORIES["maintenance"])
    if "amount" in maint.columns:
        maint = maint[maint["amount"] > 0]
    if maint.empty:
        st.caption("אין תנועות תחת מילות מפתח 'אחזקת', 'מוסך', 'תיקונים'.")
    else:
        total_m = float(maint["amount"].sum())
        st.metric("סה\"כ אחזקה", _fmt_money(total_m))
        cols = [c for c in ["date", "month", "account_name", "supplier", "description", "amount"]
                if c in maint.columns]
        st.dataframe(maint[cols], use_container_width=True, hide_index=True)


# ─── Tab 7: רכבים וכלים ─────────────────────────────────────
def _tab_vehicles_tools(df: pd.DataFrame) -> None:
    sec("שעות עבודה לפי כלי")
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    if hours.empty:
        ins("blue", "ℹ️", "אין נתוני שעות", "טען <code>hours.xlsx</code> לחודש.")
    else:
        by_tool = hours.groupby(["license_num", "tool_name"])["work_hours"].sum().reset_index()
        by_tool.columns = ["מספר רישוי", "שם כלי", "סה\"כ שעות"]
        by_tool["סה\"כ שעות"] = by_tool["סה\"כ שעות"].round(1)
        st.dataframe(by_tool.sort_values("סה\"כ שעות", ascending=False),
                     use_container_width=True, hide_index=True)

    sec("ליטר/שעה ותקנים")
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    if not solar.empty and not hours.empty:
        from core import solar_loader, hours_loader
        sm = solar_loader.aggregate_by_tool_month(solar)
        hm = hours_loader.aggregate_by_tool_month(hours)
        from pipeline import _load_tools_registry
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


# ─── Tab 9: AI / חריגות ─────────────────────────────────────
def _tab_ai_anomalies(df: pd.DataFrame, project_id: str) -> None:
    sec("חריגות שהמערכת זיהתה")
    from core import solar_loader, hours_loader
    from pipeline import _load_tools_registry

    sr = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hr = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    cr = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    sm = solar_loader.aggregate_by_tool_month(sr) if not sr.empty else pd.DataFrame()
    hm = hours_loader.aggregate_by_tool_month(hr) if not hr.empty else pd.DataFrame()

    anom = anomaly_detector.run_all_checks(cr, sm, hm, _load_tools_registry(), hr)
    if anom.empty:
        ins("green", "✓", "אין חריגות פעילות", "כל הבדיקות עברו בהצלחה.")
    else:
        disp = anom.copy()
        disp["estimated_impact_nis"] = disp["estimated_impact_nis"].round(0)
        disp.columns = ["פרויקט", "חודש", "סוג בדיקה", "חומרה",
                        "מזהה", "פרטים", "השפעה (₪)"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    sec("שאל את ה-AI על הפרויקט")
    import os
    q = st.text_area("השאלה שלך", placeholder="לדוגמה: מה הקטגוריה הכי בעייתית?",
                     key=f"ai_q_{project_id}", height=80)
    if st.button("שלח", key=f"ai_send_{project_id}", type="primary", disabled=not q.strip()):
        if not os.getenv("ANTHROPIC_API_KEY"):
            st.error("חסר ANTHROPIC_API_KEY ב-.env / secrets.")
        else:
            from core import ai_insights
            with st.spinner("Claude חושב…"):
                st.markdown(ai_insights.ask_with_context(df, q.strip(), project_id=project_id))


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
