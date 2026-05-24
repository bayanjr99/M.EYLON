"""מערכת ביקורת פרויקטי בנייה — מ. אילון אביב נכסים בע"מ.

הפעלה:
    streamlit run app.py
    או: start.bat (Windows) / ./start.sh

מבנה:
    Top bar → Filter → KPI strip → Executive summary → 6 טאבים.

נכון לעכשיו זהו שלד עיצובי. כשיהיה דאטה ב-master.parquet,
ה-placeholders יוחלפו אוטומטית בערכים אמיתיים.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Persistent logging ──────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "dashboard.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dashboard")
logger.info("=== dashboard script started ===")

# ── Imports פנימיים ────────────────────────────────────────
import pipeline
from core import anomaly_detector, project_aggregator
from ui.components import (
    blk, empty_state, exec_summary, ins, kpi_block,
    polish, render_kpi_group, render_top_bar, sec,
)
from ui.styles import LOADING_VEIL, MAIN_CSS

try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# ═══ PAGE CONFIG ═══════════════════════════════════════════
st.set_page_config(
    page_title='מ. אילון אביב נכסים בע"מ — מערכת ביקורת פרויקטים',
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ═══ Loading veil + main CSS ═══════════════════════════════
st.markdown(LOADING_VEIL, unsafe_allow_html=True)
st.markdown(MAIN_CSS, unsafe_allow_html=True)


# ═══ DATA LOAD ══════════════════════════════════════════════
@st.cache_data(show_spinner=False, ttl=300)
def _load_master() -> pd.DataFrame:
    """טוען master.parquet. ממוטמן ל-5 דקות."""
    return pipeline.load_master()


df_master = _load_master()
has_data = not df_master.empty

projects = pipeline.list_available_projects()
project_lookup = {p["project_name"]: p for p in projects}


# ═══ TOP BAR ════════════════════════════════════════════════
_now = datetime.now().strftime("%d/%m/%Y %H:%M")
if has_data:
    _meta = f'{_now} · {len(projects)} פרויקטים · {len(df_master):,} תנועות'
    _status, _status_txt = "ok", "המערכת תקינה"
else:
    _meta = f'{_now} · {len(projects)} פרויקטים · אין דאטה'
    _status, _status_txt = "warn", "ממתין לדאטה"

render_top_bar(
    company_name='מ. אילון אביב נכסים בע"מ',
    system_name="מערכת ביקורת פרויקטים",
    status=_status,
    status_text=_status_txt,
    meta_text=_meta,
)


# ═══ FILTER BAR ═════════════════════════════════════════════
with st.container():
    st.markdown('<div class="filter-marker">סינון נתונים</div>', unsafe_allow_html=True)
    fa, fb, fc, fd = st.columns([3, 3, 3, 1])
    with fa:
        if projects:
            project_name = st.selectbox(
                "פרויקט", ["כל הפרויקטים"] + list(project_lookup.keys()),
                key="f_project",
            )
        else:
            project_name = "כל הפרויקטים"
            st.caption("לא נמצאו פרויקטים ב-projects_registry.xlsx")

    project_id = project_lookup.get(project_name, {}).get("project_id") if project_name != "כל הפרויקטים" else None

    with fb:
        months_available = pipeline.list_available_months(project_id) if project_id else []
        if not months_available and has_data and "month" in df_master.columns:
            months_available = sorted(df_master["month"].dropna().unique().tolist())
        month_options = ["כל החודשים"] + months_available
        month_choice = st.selectbox("חודש", month_options, key="f_month")

    with fc:
        search_q = st.text_input(
            "חיפוש",
            key="f_search",
            placeholder="🔍 חפש ספק / כלי / מספר חשבון…",
            label_visibility="visible",
        )

    with fd:
        st.markdown(
            "<div style='font-size:11px;font-weight:600;color:#64748B;margin-bottom:6px'>&nbsp;</div>",
            unsafe_allow_html=True,
        )
        if st.button("איפוס", key="btn_reset", use_container_width=True, help="חזרה לערכי ברירת מחדל"):
            for k in ("f_project", "f_month", "f_search"):
                st.session_state.pop(k, None)
            st.rerun()


# ═══ FILTERED DF ════════════════════════════════════════════
df = df_master.copy() if has_data else df_master
if has_data:
    if project_id and "project_id" in df.columns:
        df = df[df["project_id"] == project_id]
    if month_choice != "כל החודשים" and "month" in df.columns:
        df = df[df["month"] == month_choice]
    if search_q.strip():
        q = search_q.strip().lower()
        mask = pd.Series(False, index=df.index)
        for col in ("supplier", "tool_name", "description", "account_name"):
            if col in df.columns:
                mask |= df[col].astype(str).str.lower().str.contains(q, na=False)
        df = df[mask]


# ═══ KPI computations ═══════════════════════════════════════
def _fmt_money(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"₪{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"₪{v/1_000:.0f}K"
    return f"₪{v:,.0f}"


if has_data and not df.empty:
    _total_exp = float(df[df["amount"] > 0]["amount"].sum()) if "amount" in df.columns else 0.0
    _total_inc = float(-df[df["amount"] < 0]["amount"].sum()) if "amount" in df.columns else 0.0
    _balance = _total_inc - _total_exp
    _active_proj = int(df["project_id"].nunique()) if "project_id" in df.columns else 0
    _num_tools = int(df["license_num"].dropna().nunique()) if "license_num" in df.columns else 0
    _num_suppliers = int(df["supplier"].dropna().nunique()) if "supplier" in df.columns else 0
    _anomaly_count = int(df["anomaly_flags"].astype(str).str.len().gt(2).sum()) if "anomaly_flags" in df.columns else 0
else:
    _total_exp = _total_inc = _balance = 0.0
    _active_proj = _num_tools = _num_suppliers = _anomaly_count = 0


# ═══ KPI STRIP ══════════════════════════════════════════════
_TT = {
    "exp":   "סה\"כ הוצאות מ-chashbashevet (amount חיובי) על פני הפילטרים הנוכחיים.",
    "inc":   "סה\"כ הכנסות (חשבונות 927/951/7367), מוצג כערך חיובי.",
    "bal":   "יתרה = הכנסות - הוצאות. שלילי = הוצאות גוברות על הכנסות.",
    "proj":  "מספר פרויקטים שיש להם תנועות בטווח הנבחר.",
    "tools": "מספר כלים ייחודיים (מספרי רישוי) שהיה להם תדלוק או שעות עבודה.",
    "sup":   "מספר ספקים ייחודיים בכרטיס ההנהלה.",
    "anom":  "מספר תנועות שזוהו ע\"י anomaly_detector כחריגות (סולר/שעות/חיוב גדול/מילות מפתח).",
}

_kpis_fin = [
    kpi_block("סה\"כ הוצאות", _fmt_money(_total_exp), accent="red",
              icon="ti-coin", tooltip=_TT["exp"],
              chips="חודש זה" if month_choice != "כל החודשים" else "כל החודשים"),
    kpi_block("סה\"כ הכנסות", _fmt_money(_total_inc), accent="green",
              icon="ti-cash-banknote", tooltip=_TT["inc"],
              chips="חשבונות 927/951/7367"),
    kpi_block(
        "יתרה",
        _fmt_money(_balance),
        accent="green" if _balance >= 0 else "red",
        icon="ti-wallet",
        tooltip=_TT["bal"],
        chips=f"{'עודף' if _balance >= 0 else 'גירעון'} · {abs(_balance)/_total_exp*100:.1f}% מההוצאות" if _total_exp > 0 else "",
    ),
]

_kpis_ops = [
    kpi_block("פרויקטים פעילים", str(_active_proj or len(projects)),
              accent="blue", icon="ti-buildings", tooltip=_TT["proj"],
              chips=f"מתוך {len(projects)} ברגיסטרי" if projects else ""),
    kpi_block("כלים בשטח", str(_num_tools), accent="amber",
              icon="ti-bulldozer", tooltip=_TT["tools"],
              chips="במקרה של דאטה - מתוך tools_registry.xlsx"),
    kpi_block("ספקים", str(_num_suppliers), accent="slate",
              icon="ti-truck", tooltip=_TT["sup"],
              chips="מ-chashbashevet"),
    kpi_block(
        "חריגות פעילות",
        str(_anomaly_count),
        accent="red" if _anomaly_count > 0 else "green",
        icon="ti-alert-triangle",
        tooltip=_TT["anom"],
        chips="לבדיקה בטאב חריגות" if _anomaly_count > 0 else "אין",
    ),
]

render_kpi_group(_kpis_fin, "פיננסי", "ti-cash-banknote")
render_kpi_group(_kpis_ops, "תפעולי וסיכון", "ti-activity")


# ═══ EXECUTIVE SUMMARY ══════════════════════════════════════
if has_data:
    _status_word = "good" if _balance >= 0 and _anomaly_count == 0 else "warn" if _balance >= 0 else "bad"
    _status_text = {"good": "תקין", "warn": "לבדיקה", "bad": "דורש טיפול"}[_status_word]
    exec_summary(
        title="סיכום מנהלים",
        status=_status_word,
        status_text=_status_text,
        questions=[
            ("האם יש גירעון?",
             f"{'לא' if _balance >= 0 else 'כן'} ({_fmt_money(_balance)})",
             "יתרה כוללת על פני הפילטרים"),
            ("חריגות שדורשות טיפול?",
             f"{_anomaly_count} חריגות",
             "צפה בטאב 🚨 חריגות"),
            ("הוצאה דומיננטית?",
             (lambda d: (
                 d.groupby("category")["amount"].sum().sort_values(ascending=False).index[0]
                 if "category" in d.columns and not d[d["amount"] > 0].empty else "—"
             ))(df[df["amount"] > 0] if "amount" in df.columns else df),
             "קטגוריה עם סך ההוצאות הגבוה ביותר"),
        ],
    )
else:
    exec_summary(
        title="סיכום מנהלים",
        status="warn",
        status_text="ממתין לדאטה",
        questions=[
            ("האם יש דאטה?",
             "לא",
             "master.parquet עוד לא נבנה"),
            ("פרויקטים ברגיסטרי?",
             f"{len(projects)} פרויקטים",
             "data/projects_registry.xlsx"),
            ("הצעד הבא?",
             "build_master()",
             "אחרי שמסדרים קבצי קלט בתיקיית projects/"),
        ],
    )


# ═══ TABS ═══════════════════════════════════════════════════
tab_overview, tab_project, tab_solar, tab_suppliers, tab_anomalies, tab_ai = st.tabs([
    "📊 סקירה כללית",
    "🏗️ פרויקט",
    "⛽ סולר וצמ\"ה",
    "🏢 ספקים",
    "🚨 חריגות",
    "🤖 AI",
])


# ═══ TAB: סקירה כללית ═════════════════════════════════════
with tab_overview:
    if not has_data:
        empty_state(
            icon="ti-database-off",
            title="אין עדיין דאטה לסקירה",
            body_html=(
                "כדי להתחיל לראות נתונים על פני כל הפרויקטים:"
                "<ul>"
                "<li>ודא שהפרויקטים שלך רשומים ב-<code>data/projects_registry.xlsx</code></li>"
                "<li>שים קבצי קלט ב-<code>data/projects/&lt;project_id&gt;/&lt;MM-YYYY&gt;/</code></li>"
                "<li>הרץ: <code>python -c \"from pipeline import build_master; build_master()\"</code></li>"
                "<li>רענן את הדף (F5)</li>"
                "</ul>"
            ),
            action="הצעד הראשון: סדר את חודש 12-2025 של ראשון לציון",
        )
    else:
        sec("הוצאות לפי פרויקט")
        col_a, col_b = st.columns([3, 2])
        with col_a:
            if HAS_PLOTLY and "project_name" in df.columns:
                by_proj = (df[df["amount"] > 0].groupby("project_name")["amount"].sum()
                           .sort_values(ascending=True))
                if not by_proj.empty:
                    fig = go.Figure(go.Bar(
                        x=by_proj.values, y=by_proj.index, orientation="h",
                        marker_color="#D97706", opacity=0.88,
                        text=[_fmt_money(v) for v in by_proj.values],
                        textposition="outside",
                        hovertemplate="<b>%{y}</b><br>%{x:,.0f} ₪<extra></extra>",
                    ))
                    fig.update_layout(showlegend=False, height=max(280, len(by_proj) * 36),
                                      margin=dict(l=20, r=80, t=30, b=30),
                                      paper_bgcolor="white", plot_bgcolor="white",
                                      font=dict(family="Inter,Segoe UI", size=12),
                                      xaxis=dict(visible=False),
                                      yaxis=dict(showgrid=False, tickfont=dict(size=11)))
                    st.plotly_chart(polish(fig), use_container_width=True)
                else:
                    st.caption("אין הוצאות בטווח הנבחר")
        with col_b:
            sec("הוצאות לפי קטגוריה")
            if HAS_PLOTLY and "category" in df.columns:
                by_cat = df[df["amount"] > 0].groupby("category")["amount"].sum()
                if not by_cat.empty:
                    fig = go.Figure(go.Pie(
                        labels=by_cat.index, values=by_cat.values, hole=0.55,
                        marker=dict(colors=["#D97706", "#0E5A2E", "#2563EB", "#64748B",
                                             "#A21CAF", "#DC2626", "#F59E0B", "#16A34A"]),
                        textinfo="percent", textfont=dict(size=11),
                    ))
                    fig.update_layout(showlegend=True, height=300,
                                      margin=dict(l=10, r=10, t=20, b=20),
                                      paper_bgcolor="white",
                                      font=dict(family="Inter,Segoe UI", size=11),
                                      legend=dict(orientation="v", x=1.1, y=0.5))
                    st.plotly_chart(polish(fig), use_container_width=True)

        sec("מגמת הוצאות חודשית", meta="6 חודשים אחרונים")
        if HAS_PLOTLY and "month" in df.columns:
            monthly = (df[df["amount"] > 0].groupby("month")["amount"].sum().sort_index())
            if not monthly.empty:
                fig = go.Figure(go.Scatter(
                    x=monthly.index, y=monthly.values, mode="lines+markers",
                    line=dict(color="#D97706", width=3),
                    marker=dict(size=9, color="#7C2D12"),
                    fill="tozeroy", fillcolor="rgba(217,119,6,0.1)",
                    hovertemplate="<b>%{x}</b><br>%{y:,.0f} ₪<extra></extra>",
                ))
                fig.update_layout(showlegend=False, height=280,
                                  margin=dict(l=20, r=20, t=20, b=40),
                                  paper_bgcolor="white", plot_bgcolor="white",
                                  font=dict(family="Inter,Segoe UI", size=12),
                                  yaxis=dict(gridcolor="#F1F5F9"))
                st.plotly_chart(polish(fig), use_container_width=True)


# ═══ TAB: פרויקט ═════════════════════════════════════════════
with tab_project:
    sec(f"פרויקט: {project_name}", meta=(month_choice if month_choice != "כל החודשים" else ""))
    if project_id is None:
        ins("blue", "ℹ️", "בחר פרויקט ספציפי",
            "השתמש בפילטר למעלה כדי לבחור פרויקט בודד ולראות פירוט מלא של ההוצאות, "
            "הקטגוריות הדומיננטיות וספקי הליבה.")
    elif df.empty:
        empty_state(
            icon="ti-folder-off",
            title=f"אין תנועות לפרויקט {project_name} בטווח שנבחר",
            body_html="ייתכן שלא הועלו עדיין קבצי קלט לפרויקט הזה, או שהפילטרים מסננים את כל השורות.",
        )
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("הוצאות החודש", _fmt_money(_total_exp))
        col2.metric("הכנסות החודש", _fmt_money(_total_inc))
        col3.metric("חריגות", _anomaly_count)

        st.markdown("---")
        sec("הוצאות לפי קטגוריה × חודש")
        cat_pivot = project_aggregator.category_month_matrix(df_master, project_id=project_id)
        if cat_pivot.empty:
            st.caption("אין נתונים להצגה בטווח שנבחר.")
        else:
            st.dataframe(
                cat_pivot.style.format("{:,.0f}").background_gradient(cmap="Oranges", axis=None),
                use_container_width=True,
            )

        sec("ספקים גדולים בפרויקט", meta="Top 10")
        sup_df = project_aggregator.by_supplier(df, top_n=10)
        if sup_df.empty:
            st.caption("אין נתוני ספקים.")
        else:
            st.dataframe(
                sup_df.assign(total_amount=sup_df["total_amount"].round(0)),
                use_container_width=True, hide_index=True,
            )


# ═══ TAB: סולר וצמ"ה ════════════════════════════════════════
with tab_solar:
    sec("ביקורת צריכת סולר",
        meta="ל'/ש' בפועל מול תקן הכלי (data/tools_registry.xlsx)")

    if not has_data:
        empty_state(
            icon="ti-gas-station",
            title="עוד אין נתוני תדלוק",
            body_html=(
                "כדי לראות ביקורת צריכת סולר, יש לטעון:"
                "<ul>"
                "<li><code>solar.xlsx</code> מ-Pointer/דלקן (פילטור אוטומטי לפי שם פרויקט)</li>"
                "<li><code>hours.xlsx</code> מהמזכירה (שעות עבודה לכל כלי)</li>"
                "</ul>"
                "המערכת תחבר ביניהם דרך מספר רישוי (license_num) ותחשב ל'/שעה בפועל."
            ),
            action="תקני הצריכה כבר מוגדרים: 24 כלים ב-tools_registry.xlsx",
        )
    else:
        ins("amber", "⚠️", "בדיקה ראשית",
            "צריכת ל'/ש' מעל <b>תקן עליון × 1.15</b> מסומנת כחריגה. "
            "נזק כספי מחושב לפי 7.5 ₪/ליטר.")

        sec("טבלת כלים - חודש נוכחי")
        from core import solar_loader as _sl, hours_loader as _hl
        _solar_rows = df[df["source"] == "solar"] if "source" in df.columns else pd.DataFrame()
        _hours_rows = df[df["source"] == "hours"] if "source" in df.columns else pd.DataFrame()
        _solar_monthly = _sl.aggregate_by_tool_month(_solar_rows) if not _solar_rows.empty else pd.DataFrame()
        _hours_monthly = _hl.aggregate_by_tool_month(_hours_rows) if not _hours_rows.empty else pd.DataFrame()
        _tools_reg = pipeline._load_tools_registry()
        _excess = anomaly_detector.detect_solar_excess(_solar_monthly, _hours_monthly, _tools_reg)

        if _excess.empty:
            st.caption("אין נתוני סולר-מול-שעות בטווח שנבחר, או שאין חריגות.")
        else:
            display = _excess.copy()
            display["actual_lph"] = display["actual_lph"].round(1)
            display["damage_estimate_nis"] = display["damage_estimate_nis"].round(0)
            display.columns = ["מס' רישוי", "שם כלי", "חודש", "סה\"כ ל'", "סה\"כ שעות",
                               "ל'/ש' בפועל", "תקן עליון", "חריגה (ל')",
                               "נזק כספי (₪)", "חומרה"]
            st.dataframe(display, use_container_width=True, hide_index=True)

        sec("Drill-down לכלי בודד")
        if not _solar_rows.empty:
            tools_list = _solar_rows[["license_num", "tool_name"]].dropna().drop_duplicates()
            options = {f"{int(r['license_num'])} · {r['tool_name']}": int(r["license_num"])
                       for _, r in tools_list.iterrows()}
            if options:
                pick = st.selectbox("בחר כלי", list(options.keys()), key="drill_tool")
                lic = options[pick]
                tool_solar = _solar_rows[_solar_rows["license_num"] == lic][
                    ["date", "tool_name", "liters", "engine_hours"]
                ].sort_values("date")
                tool_hours = _hours_rows[_hours_rows["license_num"] == lic][
                    ["date", "work_hours"]
                ].sort_values("date") if not _hours_rows.empty else pd.DataFrame()
                cA, cB = st.columns(2)
                with cA:
                    st.caption("תדלוקים")
                    st.dataframe(tool_solar, use_container_width=True, hide_index=True)
                with cB:
                    st.caption("שעות עבודה")
                    st.dataframe(tool_hours, use_container_width=True, hide_index=True)
        else:
            st.caption("אין נתוני תדלוק לכלים בטווח שנבחר.")


# ═══ TAB: ספקים ═════════════════════════════════════════════
with tab_suppliers:
    sec("ניתוח ספקים", meta=f"{_num_suppliers} ספקים פעילים")

    if not has_data or "supplier" not in df.columns:
        empty_state(
            icon="ti-truck-delivery",
            title="עוד אין נתוני ספקים",
            body_html=(
                "ספקים מחולצים אוטומטית מעמודת 'פרטים' ב-<code>chashbashevet.xlsx</code> "
                "(בדרך כלל החלק לפני המקף הראשון). "
                "אחרי build_master() יוצגו כאן top 30 הספקים עם פילוח לפי פרויקט."
            ),
        )
    else:
        sec("Top 30 ספקים")
        top_sup = project_aggregator.by_supplier(df, top_n=30)
        if top_sup.empty:
            st.caption("אין נתוני ספקים בטווח שנבחר.")
        else:
            disp = top_sup.copy()
            disp["total_amount"] = disp["total_amount"].round(0)
            disp.columns = ["ספק", "סה\"כ (₪)", "תנועות", "פרויקטים", "תאריך ראשון", "תאריך אחרון"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

        sec("מטריצת ספק × חודש", meta="Top 20")
        matrix = project_aggregator.supplier_month_matrix(df, top_n=20)
        if matrix.empty:
            st.caption("אין מספיק נתונים למטריצה.")
        else:
            st.dataframe(
                matrix.style.format("{:,.0f}").background_gradient(cmap="Blues", axis=None),
                use_container_width=True,
            )


# ═══ TAB: חריגות ═══════════════════════════════════════════
with tab_anomalies:
    sec("חריגות מערכת הביקורת",
        meta="5 בדיקות אוטומטיות + AI insights")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.selectbox("חומרה", ["הכל", "high", "medium", "low"], key="anom_severity")
    with col2:
        st.selectbox("סוג", ["הכל", "solar_excess", "solar_without_hours",
                              "hours_excessive", "hours_negative",
                              "large_transaction", "suspicious_description"],
                     key="anom_type")
    with col3:
        st.selectbox("סטטוס", ["open", "reviewed", "dismissed"], key="anom_status")

    st.markdown("---")

    # חישוב מלא של טבלת חריגות מתוך הדאטה המסונן
    if has_data:
        from core import solar_loader as _sl2, hours_loader as _hl2
        _sr = df[df["source"] == "solar"] if "source" in df.columns else pd.DataFrame()
        _hr = df[df["source"] == "hours"] if "source" in df.columns else pd.DataFrame()
        _cr = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
        _sm = _sl2.aggregate_by_tool_month(_sr) if not _sr.empty else pd.DataFrame()
        _hm = _hl2.aggregate_by_tool_month(_hr) if not _hr.empty else pd.DataFrame()
        _tr = pipeline._load_tools_registry()
        anom_df = anomaly_detector.run_all_checks(
            df_master=_cr,
            df_solar_monthly=_sm,
            df_hours_monthly=_hm,
            tools_registry=_tr,
            df_hours_daily=_hr,
        )
    else:
        anom_df = pd.DataFrame()

    # פילטור לפי הבחירות בתפריטים
    sev_pick = st.session_state.get("anom_severity", "הכל")
    type_pick = st.session_state.get("anom_type", "הכל")
    if not anom_df.empty:
        if sev_pick != "הכל" and "severity" in anom_df.columns:
            anom_df = anom_df[anom_df["severity"] == sev_pick]
        if type_pick != "הכל" and "check_type" in anom_df.columns:
            anom_df = anom_df[anom_df["check_type"] == type_pick]

    if anom_df.empty:
        ins("green", "✓", "אין חריגות פעילות",
            "כל הבדיקות עברו בהצלחה. ייתכן שעדיין לא נטענו נתונים — בנה את ה-master ובדוק שוב.")
    else:
        total_impact = float(anom_df["estimated_impact_nis"].sum())
        ins("red", "🚨", f"זוהו {len(anom_df)} חריגות",
            f"השפעה כספית מצטברת משוערת: <b>{_fmt_money(total_impact)}</b>")
        disp = anom_df.copy()
        disp["estimated_impact_nis"] = disp["estimated_impact_nis"].round(0)
        disp.columns = ["פרויקט", "חודש", "סוג בדיקה", "חומרה",
                        "מזהה", "פרטים", "השפעה (₪)"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    with st.expander("💡 הסבר על הבדיקות"):
        st.markdown("""
        **5 הבדיקות שהמערכת מריצה אוטומטית בכל בנייה של master:**

        1. **חריגת סולר** — ל'/ש' בפועל > תקן עליון × 1.15
        2. **תדלוקים ללא שעות** — סולר > 0 אבל שעות = 0 (לא רלוונטי לגנרטור/רכב)
        3. **שעות חריגות** — יום עם > 14 שעות עבודה, או שלילי
        4. **חיובים גדולים** — סכום > 100,000 ₪
        5. **מילות מפתח חשודות** — "לבטל", "טעות", "תיקון" בתיאור

        אפשר לראות את הקבועים והלוגיקה ב-`core/anomaly_detector.py`.
        """)


# ═══ TAB: AI ════════════════════════════════════════════════
with tab_ai:
    sec("שאל את המערכת בשפה חופשית",
        meta="Claude Haiku 4.5 · דורש ANTHROPIC_API_KEY ב-.env")

    with st.expander("💡 שאלות לדוגמה"):
        st.markdown("""
        - מה הכלי הכי בעייתי החודש?
        - השווה את ספק "פז" בין כל הפרויקטים
        - סכם את החודש האחרון בפרויקט ראשון לציון
        - אילו חריגות סולר הכי משמעותיות כספית?
        - מה האחוז של עלות הסולר מסך ההוצאות?
        """)

    question = st.text_area(
        "השאלה שלך",
        placeholder="לדוגמה: מה הייתה ההוצאה הגדולה ביותר השבוע?",
        key="ai_q",
        height=100,
    )
    submitted = st.button("שלח שאלה", type="primary", disabled=not question.strip())

    if submitted and question.strip():
        if not has_data:
            st.warning("אין דאטה לשלוח ל-AI. בנה את master.parquet קודם.")
        elif not os.getenv("ANTHROPIC_API_KEY"):
            st.error("חסר ANTHROPIC_API_KEY. צור קובץ .env בשורש הפרויקט עם המפתח.")
        else:
            from ai_tools import ask_ai_about_data
            with st.spinner("שואל את Claude..."):
                ctx = f"פרויקטים פעילים: {_active_proj}, סה\"כ הוצאות: {_fmt_money(_total_exp)}, חריגות: {_anomaly_count}"
                answer = ask_ai_about_data(df, question.strip(), context=ctx)
            st.markdown(answer)


# ═══ FOOTER ═════════════════════════════════════════════════
st.markdown("---")
_footer_left = f"בנוי על נתונים מ-`data/master.parquet`"
_footer_right = f"גרסת שלד · {len(df_master):,} שורות במאסטר · {datetime.now().strftime('%d/%m/%Y %H:%M')}"
st.markdown(
    f'<div style="display:flex;justify-content:space-between;font-size:11px;color:#94A3B8;'
    f'padding:8px 0">'
    f'<span>{_footer_left}</span>'
    f'<span>{_footer_right}</span>'
    f'</div>',
    unsafe_allow_html=True,
)
