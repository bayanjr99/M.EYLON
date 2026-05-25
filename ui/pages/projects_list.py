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


def _render_new_project_form(existing_projects: list[dict]) -> None:
    """טופס להוספת פרויקט חדש מתוך המסך הראשי."""
    import streamlit as st
    from datetime import date as date_cls
    from core.project_store import (
        make_safe_project_id, validate_project_id, create_project, VALID_STATUSES,
    )

    existing_ids = {p.get("project_id", "") for p in existing_projects}

    # אם המשתמש מקליד שם, נציע project_id דינמי
    typed_name = st.session_state.get("new_proj_name_input", "")
    suggested_id = make_safe_project_id(typed_name, existing_ids) if typed_name else ""

    with st.form("new_project_form", clear_on_submit=False):
        st.markdown("### ➕ פרויקט חדש")
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input(
                "שם פרויקט בעברית *",
                key="new_proj_name_input",
            )
            site = st.text_input(
                "שם אתר (אם שונה משם הפרויקט)",
            )
            client = st.text_input("שם לקוח")
        with c2:
            pid_default = suggested_id if suggested_id else ""
            pid = st.text_input(
                "project_id (אנגלית, lower_case, ייחודי) *",
                value=pid_default,
            )
            status = st.selectbox("סטטוס", VALID_STATUSES, index=0)
            start_date = st.date_input(
                "תאריך התחלה", value=date_cls.today(), format="DD/MM/YYYY",
            )
        notes = st.text_area("הערות")

        col_submit, col_cancel = st.columns([3, 1])
        with col_submit:
            submitted = st.form_submit_button(
                "✅ צור פרויקט", type="primary", use_container_width=True,
            )
        with col_cancel:
            cancelled = st.form_submit_button(
                "ביטול", use_container_width=True,
            )

        if cancelled:
            st.session_state.pop("show_new_project_form", None)
            st.rerun()

        if submitted:
            if not name or not name.strip():
                st.error("שם פרויקט חובה")
                return
            # אימות + יצירה
            final_pid = (pid or suggested_id or "").strip()
            if not final_pid:
                final_pid = make_safe_project_id(name, existing_ids)
            ok_v, err_v = validate_project_id(final_pid)
            if not ok_v:
                st.error(err_v)
                return
            ok, msg, created_id = create_project({
                "project_id": final_pid,
                "project_name": name.strip(),
                "site_name": (site or "").strip(),
                "client_name": (client or "").strip(),
                "status": status,
                "start_date": start_date.strftime("%Y-%m-%d") if start_date else "",
                "notes": (notes or "").strip(),
            })
            if not ok:
                st.error(msg)
                return
            st.success(f"✅ {msg}. ID: {created_id}")
            st.cache_data.clear()
            st.session_state.pop("show_new_project_form", None)
            # ניווט אוטומטי לפרויקט החדש
            st.session_state["selected_project_id"] = created_id
            st.rerun()


def _render_add_project_card() -> None:
    """כרטיס 'הוסף פרויקט' באותו גודל וצורה ככרטיסי הפרויקטים."""
    import streamlit as st
    # Card content (matches project card visual rhythm: ~200px content)
    st.markdown(
        """
        <div class="section-card" style="padding:18px 22px;display:flex;
        flex-direction:column;align-items:center;justify-content:center;
        text-align:center;border:2px dashed var(--brand-primary-mid);
        background:var(--brand-primary-soft);min-height:215px">
          <div style="display:flex;align-items:center;justify-content:center;
            width:64px;height:64px;border-radius:50%;
            background:var(--brand-primary);color:#fff;font-size:36px;
            font-weight:700;line-height:1;margin-bottom:14px;
            box-shadow:0 3px 10px rgba(22,163,74,.32)">+</div>
          <div style="font-size:16px;font-weight:800;color:var(--brand-primary-dark);
            line-height:1.3;margin-bottom:4px">הוסף פרויקט חדש</div>
          <div style="font-size:11.5px;color:var(--ink-soft);line-height:1.4">
            לחץ למטה כדי להגדיר פרויקט חדש
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("הוסף פרויקט חדש", key="btn_new_project_card",
                   use_container_width=True, type="primary"):
        st.session_state["show_new_project_form"] = True
        st.rerun()


def render_projects_list(df_master: pd.DataFrame, projects: list[dict]) -> None:
    """מציג רשת כרטיסים — אחד לכל פרויקט + כרטיס 'הוסף פרויקט' בסוף.

    Args:
        df_master: ה-master.parquet (לחישוב KPIs לכל פרויקט).
        projects: תוצאת pipeline.list_available_projects().
    """
    import streamlit as st

    # ── אם הטופס פתוח - מציגים אותו במקום הרשת ──
    if st.session_state.get("show_new_project_form"):
        _render_new_project_form(projects)
        return

    if not projects:
        # אין פרויקטים - מציגים רק את כרטיס ההוספה
        sec("ברוך הבא", meta="עדיין אין פרויקטים במערכת")
        col_center, _ = st.columns([1, 1])
        with col_center:
            _render_add_project_card()
        return

    sec("בחר פרויקט", meta=f"{len(projects)} פרויקטים ברגיסטרי")

    # רשת כרטיסים: כרטיסי פרויקטים + כרטיס הוסף בסוף
    cols_per_row = 2
    # בונים רשימה של "תאי תצוגה" - dict עם project או "add"
    cells: list[dict | str] = list(projects) + ["__ADD__"]
    rows = [cells[i:i + cols_per_row] for i in range(0, len(cells), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row)
        for col, cell in zip(cols, row):
            with col:
                if cell == "__ADD__":
                    _render_add_project_card()
                else:
                    _render_project_card(cell, df_master)


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
