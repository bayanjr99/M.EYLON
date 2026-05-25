"""דף נחיתה: רשימת פרויקטים ככרטיסים.

כל כרטיס מציג סיכום פיננסי + כפתור "פתח פרויקט" שמכניס לדף הפרויקט.
הניווט מבוסס על st.session_state.selected_project_id.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import project_aggregator
from ui.components import empty_state, sec


def _fmt_money(v: float) -> str:
    """₪123K / ₪1.2M / ₪987 — קומפקטי לכרטיסים."""
    if abs(v) >= 1_000_000:
        return f"₪{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"₪{v/1_000:.0f}K"
    return f"₪{v:,.0f}"


def _status_pill_html(status: str) -> str:
    """תרגום סטטוס לכרטיס pill עם צבע."""
    cls_map = {"active": "ok", "פעיל": "ok", "paused": "warn",
               "מושהה": "warn", "closed": "crit", "סגור": "crit",
               "on_hold": "warn", "completed": "ok", "הושלם": "ok"}
    label_map = {"active": "פעיל", "paused": "מושהה", "closed": "סגור",
                 "on_hold": "מושהה", "completed": "הושלם"}
    cls = cls_map.get(str(status).lower(), "warn")
    label = label_map.get(str(status).lower(), str(status) or "—")
    return f'<span class="status-pill {cls}">{label}</span>'


def _profit_color(profit: float) -> str:
    """ירוק לרווח, אדום לגירעון, אפור לאפס."""
    if profit > 0:
        return "var(--status-good)"
    if profit < 0:
        return "var(--status-bad)"
    return "var(--ink-faint)"


def render_projects_list(df_master: pd.DataFrame, projects: list[dict]) -> None:
    """מציג רשת כרטיסים — אחד לכל פרויקט מ-projects_registry.

    Args:
        df_master: ה-master.parquet (לחישוב KPIs לכל פרויקט).
        projects: תוצאת pipeline.list_available_projects().
    """
    if not projects:
        empty_state(
            icon="ti-buildings",
            title="לא נמצאו פרויקטים",
            body_html=(
                "כדי להתחיל, רשום פרויקט ב-"
                "<code>data/projects_registry.xlsx</code> "
                "ואז הוסף את התיקייה תחת "
                "<code>data/projects/&lt;project_id&gt;/</code>"
            ),
        )
        return

    sec("בחר פרויקט", meta=f"{len(projects)} פרויקטים ברגיסטרי")

    # 2 כרטיסים בכל שורה (responsive — Streamlit עוטף אוטומטית)
    cols_per_row = 2
    rows = [projects[i:i + cols_per_row] for i in range(0, len(projects), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row)
        for col, proj in zip(cols, row):
            with col:
                _render_project_card(proj, df_master)


def _render_project_card(proj: dict, df_master: pd.DataFrame) -> None:
    """כרטיס יחיד - שם/לקוח/סטטוס/KPIs/כפתור."""
    project_id = proj.get("project_id", "")
    project_name = proj.get("project_name", project_id) or project_id
    client = proj.get("client_name") or proj.get("notes") or "—"
    status = proj.get("status", "active")

    summary = project_aggregator.project_summary(df_master, project_id)

    # ── HTML של הכרטיס ──
    if summary["has_data"]:
        profit = summary["profit"]
        profit_color = _profit_color(profit)
        kpi_block_html = f"""
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:14px 0">
          <div>
            <div style="font-size:10px;color:var(--ink-faint);font-weight:700;
              text-transform:uppercase;letter-spacing:.8px">הכנסות</div>
            <div style="font-size:18px;font-weight:800;color:var(--status-good);
              direction:ltr;text-align:right">{_fmt_money(summary['revenue'])}</div>
          </div>
          <div>
            <div style="font-size:10px;color:var(--ink-faint);font-weight:700;
              text-transform:uppercase;letter-spacing:.8px">הוצאות</div>
            <div style="font-size:18px;font-weight:800;color:var(--status-bad);
              direction:ltr;text-align:right">{_fmt_money(summary['expenses'])}</div>
          </div>
          <div>
            <div style="font-size:10px;color:var(--ink-faint);font-weight:700;
              text-transform:uppercase;letter-spacing:.8px">רווח / הפסד</div>
            <div style="font-size:20px;font-weight:800;color:{profit_color};
              direction:ltr;text-align:right">{_fmt_money(profit)}</div>
          </div>
          <div>
            <div style="font-size:10px;color:var(--ink-faint);font-weight:700;
              text-transform:uppercase;letter-spacing:.8px">% רווחיות</div>
            <div style="font-size:20px;font-weight:800;color:{profit_color};
              direction:ltr;text-align:right">{summary['profit_pct']:.1f}%</div>
          </div>
        </div>
        <div style="font-size:11px;color:var(--ink-soft);margin-bottom:6px">
          {summary['num_transactions']:,} תנועות · {summary['num_suppliers']} ספקים ·
          {summary['num_tools']} כלים{' · <span style="color:var(--status-bad);font-weight:700">'
          + str(summary['num_anomalies']) + ' חריגות</span>' if summary['num_anomalies'] else ''}
        </div>
        """
    else:
        kpi_block_html = """
        <div style="background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:10px;
          padding:18px;margin:14px 0;text-align:center;color:#64748B;font-size:12px">
          <i class="ti ti-database-off" style="font-size:24px;color:#94A3B8;display:block;
            margin-bottom:6px"></i>
          <b>אין עדיין נתונים לפרויקט זה</b><br>
          <span style="font-size:11px">הוסף קבצי חודש ל-
          <code style="background:#fff;padding:1px 5px;border-radius:3px">data/projects/{}/&lt;MM-YYYY&gt;/</code>
          </span>
        </div>
        """.format(project_id)

    st.markdown(
        f"""
        <div class="section-card" style="padding:18px 22px;display:flex;flex-direction:column">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
            <div style="min-width:0;flex:1">
              <div style="font-size:16px;font-weight:800;color:var(--ink-strong);
                line-height:1.3;margin-bottom:4px">{project_name}</div>
              <div style="font-size:11.5px;color:var(--ink-soft)">
                לקוח: <b style="color:var(--ink-mid)">{client}</b>
              </div>
            </div>
            {_status_pill_html(status)}
          </div>
          {kpi_block_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # כפתור Streamlit נפרד (לא ניתן לשים בתוך HTML)
    if st.button("פתח פרויקט ←", key=f"open_{project_id}",
                 use_container_width=True, type="primary"):
        st.session_state["selected_project_id"] = project_id
        st.rerun()
