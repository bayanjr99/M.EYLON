"""דף נחיתה: רשימת פרויקטים ככרטיסים.

כל כרטיס מציג סיכום פיננסי + כפתור "פתח פרויקט" שמכניס לדף הפרויקט.
הניווט מבוסס על st.session_state.selected_project_id.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import project_aggregator
from ui.components import empty_state, sec, kpi_block, render_kpi_group
from ui.formatters import format_currency


def _fmt_money(v: float) -> str:
    """פורמט מלא: ₪1,250,000."""
    return format_currency(v, blank="₪0")


def _status_pill_html(status: str) -> str:
    """תג סטטוס לפי 5 סטטוסים."""
    from core.project_store import validate_project_status, STATUS_HE
    s = validate_project_status(status)
    cls = {"active": "ok", "completed": "neutral",
           "future": "info", "paused": "warn",
           "archived": "crit"}.get(s, "warn")
    label = STATUS_HE.get(s, s)
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
        make_safe_project_id, validate_project_id, create_project,
        VALID_STATUSES, STATUS_HE,
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
                "מזהה פרויקט (אנגלית, אותיות קטנות, ייחודי) *",
                value=pid_default,
            )
            status_he = st.selectbox(
                "סטטוס", [STATUS_HE[s] for s in VALID_STATUSES], index=0,
            )
            start_date = st.date_input(
                "תאריך התחלה", value=date_cls.today(), format="DD/MM/YYYY",
            )
            end_date = st.date_input(
                "תאריך סיום (אופציונלי)", value=None, format="DD/MM/YYYY",
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
            # תרגום סטטוס מעברית לקוד
            status_code = next((k for k, v in STATUS_HE.items() if v == status_he),
                                "active")
            ok, msg, created_id = create_project({
                "project_id": final_pid,
                "project_name": name.strip(),
                "site_name": (site or "").strip(),
                "client_name": (client or "").strip(),
                "status": status_code,
                "start_date": start_date.strftime("%Y-%m-%d") if start_date else "",
                "end_date": end_date.strftime("%Y-%m-%d") if end_date else "",
                "notes": (notes or "").strip(),
            })
            if not ok:
                st.error(msg)
                return
            st.success(f"✅ {msg}. מזהה: {created_id}")
            st.cache_data.clear()
            st.session_state.pop("show_new_project_form", None)
            # ניווט אוטומטי לפרויקט החדש
            st.session_state["selected_project_id"] = created_id
            st.rerun()


def _render_edit_project_form(project_id: str) -> None:
    """טופס עריכת פרטי פרויקט קיים.

    project_id קבוע (לא ניתן לעריכה כדי לא לשבור נתיבים).
    """
    import streamlit as st
    from datetime import date as date_cls
    from core.project_store import (
        get_project_by_id, update_project,
        VALID_STATUSES, STATUS_HE, validate_project_status,
    )

    proj = get_project_by_id(project_id)
    if proj is None:
        st.error(f"פרויקט '{project_id}' לא נמצא")
        if st.button("← חזרה לרשימה", key="edit_back_notfound"):
            st.session_state.pop("edit_project_id", None)
            st.rerun()
        return

    def _date_or_none(v):
        # None / NaN / NaT / "" / "nan" / "nat" → None
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        s = str(v).strip()
        if not s or s.lower() in ("nan", "nat", "none"):
            return None
        try:
            ts = pd.to_datetime(v, errors="coerce")
            if ts is None or pd.isna(ts):
                return None
            return ts.date()
        except Exception:
            return None

    current_status = validate_project_status(proj.get("status"))
    current_status_he = STATUS_HE.get(current_status, "פעיל")
    status_options = [STATUS_HE[s] for s in VALID_STATUSES]

    with st.form("edit_project_form", clear_on_submit=False):
        st.markdown(f"### ✏️ עריכת פרויקט — `{project_id}`")
        st.caption("מזהה הפרויקט קבוע ולא ניתן לערוך כדי לא לשבור נתונים קיימים.")

        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("שם פרויקט *",
                                  value=_clean_text(proj.get("project_name")))
            site = st.text_input("שם אתר",
                                  value=_clean_text(proj.get("site_name")))
            client = st.text_input("שם לקוח",
                                    value=_clean_text(proj.get("client_name")))
        with c2:
            status_he = st.selectbox(
                "סטטוס", status_options,
                index=status_options.index(current_status_he)
                      if current_status_he in status_options else 0,
            )
            start_date = st.date_input(
                "תאריך התחלה",
                value=_date_or_none(proj.get("start_date")) or date_cls.today(),
                format="DD/MM/YYYY",
            )
            end_date = st.date_input(
                "תאריך סיום (אופציונלי)",
                value=_date_or_none(proj.get("end_date")),
                format="DD/MM/YYYY",
            )

        notes = st.text_area("הערות", value=_clean_text(proj.get("notes")))

        col_save, col_cancel = st.columns([3, 1])
        with col_save:
            submitted = st.form_submit_button(
                "💾 שמור שינויים", type="primary", use_container_width=True,
            )
        with col_cancel:
            cancelled = st.form_submit_button("ביטול", use_container_width=True)

        if cancelled:
            st.session_state.pop("edit_project_id", None)
            st.rerun()

        if submitted:
            if not name or not name.strip():
                st.error("שם פרויקט חובה")
                return
            status_code = next((k for k, v in STATUS_HE.items() if v == status_he),
                                "active")
            ok, msg = update_project(project_id, {
                "project_name": name.strip(),
                "site_name": (site or "").strip(),
                "client_name": (client or "").strip(),
                "status": status_code,
                "start_date": start_date.strftime("%Y-%m-%d") if start_date else "",
                "end_date": end_date.strftime("%Y-%m-%d") if end_date else "",
                "notes": (notes or "").strip(),
            })
            if not ok:
                st.error(msg)
                return
            st.success("✅ הפרויקט עודכן בהצלחה")
            st.cache_data.clear()
            st.session_state.pop("edit_project_id", None)
            st.rerun()

    # ── אזור מסוכן: מחיקת פרויקט ──
    _render_delete_project_section(project_id)


def _render_delete_project_section(project_id: str) -> None:
    """אזור מסוכן בתחתית טופס העריכה — מחיקת פרויקט עם 2 שלבי אישור.

    שלב 1: לחיצה על "הצג אפשרויות מחיקה" → חושף את האזור.
    שלב 2: הקלדת project_id מדויקת + לחיצה על "מחק לצמיתות".

    המחיקה: התיקייה עוברת ל-data/.trash/<id>_<timestamp>/, ולא
    נמחקת באמת — ניתן לשחזור ידני אם זו טעות.
    """
    import streamlit as st
    from core.project_store import delete_project, PROJECTS_DIR

    pdir = PROJECTS_DIR / project_id
    folder_exists = pdir.exists()
    n_months = 0
    n_files = 0
    if folder_exists:
        try:
            month_dirs = [d for d in pdir.iterdir() if d.is_dir() and "-" in d.name]
            n_months = len(month_dirs)
            n_files = sum(1 for _ in pdir.rglob("*") if _.is_file())
        except Exception:
            pass

    st.markdown("---")

    # ── ארכיון: חלופה רכה למחיקה ──
    from core.project_store import update_project, get_project_by_id
    proj = get_project_by_id(project_id) or {}
    current = proj.get("status")
    if current != "archived":
        a_col, _ = st.columns([2, 5])
        with a_col:
            if st.button("📦 העבר לארכיון",
                           key=f"archive_btn_{project_id}",
                           use_container_width=True,
                           help="חלופה בטוחה למחיקה: הפרויקט יוסתר מהרשימה הראשית "
                                "אך כל הנתונים יישמרו. ניתן להחזיר בכל עת."):
                ok, msg = update_project(project_id, {"status": "archived"})
                if ok:
                    st.success(f"✅ הפרויקט הועבר לארכיון. {msg}")
                    st.cache_data.clear()
                    st.session_state.pop("edit_project_id", None)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        a_col, _ = st.columns([2, 5])
        with a_col:
            if st.button("📤 הוצא מארכיון",
                           key=f"unarchive_btn_{project_id}",
                           use_container_width=True, type="primary"):
                ok, msg = update_project(project_id, {"status": "active"})
                if ok:
                    st.success("✅ הפרויקט הוחזר ממצב ארכיון לפעיל.")
                    st.cache_data.clear()
                    st.session_state.pop("edit_project_id", None)
                    st.rerun()
                else:
                    st.error(msg)

    with st.expander("🗑 מחיקת פרויקט (אזור מסוכן)", expanded=False):
        st.warning(
            f"⚠️ פעולה זו תסיר את הפרויקט **`{project_id}`** מהמערכת. "
            f"התיקייה ({n_months} חודשים · {n_files} קבצים) "
            "תועבר לסל מיחזור (`data/.trash/`) ולא תימחק לצמיתות — "
            "ניתן לשחזר ידנית במקרה של טעות."
        )

        confirm_key = f"del_proj_confirm_{project_id}"
        typed = st.text_input(
            f"כדי לאשר את המחיקה, הקלד מדויק את מזהה הפרויקט: "
            f"`{project_id}`",
            key=confirm_key,
            placeholder=project_id,
        )

        can_delete = typed.strip() == project_id

        delete_folder_too = st.checkbox(
            "העבר גם את התיקייה לסל מיחזור (מומלץ)",
            value=True,
            key=f"del_proj_folder_{project_id}",
            help="אם לא תסומן — הפרויקט יוסר רק מהרגיסטרי, התיקייה תישאר במקום.",
        )

        if st.button("🗑 מחק לצמיתות", type="secondary",
                       disabled=not can_delete,
                       key=f"del_proj_btn_{project_id}",
                       use_container_width=True):
            ok, msg, trash_path = delete_project(
                project_id, delete_folder=delete_folder_too,
            )
            if not ok:
                st.error(msg)
                return
            st.success(f"✅ {msg}")
            if trash_path:
                st.caption(f"שוחזר ב: `{trash_path}`")
            st.cache_data.clear()
            st.session_state.pop("edit_project_id", None)
            st.session_state.pop("selected_project_id", None)
            st.rerun()


def _render_add_project_card() -> None:
    """כרטיס 'הוסף פרויקט' באותו גובה ועיצוב ככרטיסי הפרויקטים.

    מבנה מקביל לכרטיס פרויקט:
    - section-card עם padding זהה (18px 22px)
    - מבנה פנימי: כותרת למעלה + תוכן ממורכז + סיכום בתחתית
    - גובה כולל ~265px כדי להתאים לפרויקט עם 4 KPIs
    """
    import streamlit as st
    st.markdown(
        """
        <div class="section-card" style="padding:18px 22px;display:flex;
        flex-direction:column;border:1.5px dashed var(--brand-primary-mid);
        background:var(--brand-primary-soft);min-height:235px">
          <!-- Header line (matches project card header alignment) -->
          <div style="font-size:13px;font-weight:700;color:var(--brand-primary-dark);
            letter-spacing:.3px;margin-bottom:4px">פרויקט חדש</div>
          <div style="font-size:11.5px;color:var(--ink-soft);margin-bottom:18px">
            ניתן להגדיר אתר, לקוח, סטטוס ותאריך התחלה
          </div>
          <!-- Centered circle + label (the eye-catching CTA) -->
          <div style="flex:1;display:flex;flex-direction:column;
            align-items:center;justify-content:center;text-align:center">
            <div style="display:flex;align-items:center;justify-content:center;
              width:58px;height:58px;border-radius:50%;
              background:var(--brand-primary);color:#fff;font-size:32px;
              font-weight:300;line-height:1;margin-bottom:10px;
              box-shadow:0 3px 12px rgba(22,163,74,.32)">+</div>
            <div style="font-size:14px;font-weight:800;color:var(--brand-primary-dark);
              line-height:1.2">הוסף פרויקט</div>
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
    from core.project_store import validate_project_status, STATUS_HE, VALID_STATUSES

    # ── אם טופס יצירה פתוח - מציגים אותו במקום הרשת ──
    if st.session_state.get("show_new_project_form"):
        _render_new_project_form(projects)
        return

    # ── אם טופס עריכה פתוח - מציגים אותו במקום הרשת ──
    edit_pid = st.session_state.get("edit_project_id")
    if edit_pid:
        _render_edit_project_form(edit_pid)
        return

    if not projects:
        # אין פרויקטים - מציגים רק את כרטיס ההוספה
        sec("ברוך הבא", meta="עדיין אין פרויקטים במערכת")
        col_center, _ = st.columns([1, 1])
        with col_center:
            _render_add_project_card()
        return

    # ── סקירה כללית של כל החברה (סיכום פורטפוליו) ──
    _render_portfolio_overview(df_master, projects)

    # ── פילטר סטטוס: הכל / פעיל / הסתיים / עתידי / ארכיון ──
    # "הכל" (ברירת מחדל) מציג את כל הפרויקטים. שאר האופציות מסננות
    # לפי הסטטוס הספציפי.
    STATUS_FILTER_ORDER = ["active", "completed", "future", "archived"]
    filter_options = ["הכל"] + [STATUS_HE[s] for s in STATUS_FILTER_ORDER]
    f_col, _ = st.columns([1, 3])
    with f_col:
        chosen = st.selectbox("פילטר לפי סטטוס", filter_options, index=0,
                                key="proj_status_filter")

    if chosen == "הכל":
        filtered = projects
    else:
        # סטטוס ספציפי שנבחר (פעיל / הסתיים / עתידי / ארכיון)
        target = next((k for k, v in STATUS_HE.items() if v == chosen), None)
        filtered = [p for p in projects
                    if validate_project_status(p.get("status")) == target]

    sec("בחר פרויקט",
        meta=f"מציג {len(filtered)} מתוך {len(projects)} פרויקטים")

    if not filtered:
        st.caption(f"אין פרויקטים בסטטוס '{chosen}'.")
        # עדיין מציגים את כרטיס ההוספה
        col_center, _ = st.columns([1, 1])
        with col_center:
            _render_add_project_card()
        return

    # רשת כרטיסים: כרטיסי פרויקטים + כרטיס הוסף בסוף
    cols_per_row = 2
    cells: list[dict | str] = list(filtered) + ["__ADD__"]
    rows = [cells[i:i + cols_per_row] for i in range(0, len(cells), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row)
        for col, cell in zip(cols, row):
            with col:
                if cell == "__ADD__":
                    _render_add_project_card()
                else:
                    _render_project_card(cell, df_master)


def _render_portfolio_overview(df_master: pd.DataFrame,
                                projects: list[dict]) -> None:
    """סקירת פורטפוליו: KPI מצרפי של כל החברה בראש מסך הנחיתה.

    משתמש באותן פונקציות analytics כמו מסך הפרויקט — כך הסכומים מסונכרנים
    עם דפי הפרויקט הבודדים (הכנסות/הוצאות נטו לפי real_income_mask).
    """
    if df_master is None or df_master.empty:
        return

    # מצרפים את אותו project_summary שמופיע בכרטיסים — כך שהבאנר
    # שווה בדיוק לסכום הכרטיסים (עקביות מלאה, ללא ניפוח הכנסות מזיכויים).
    revenue = expenses = 0.0
    n_with_data = 0
    for p in projects:
        s = project_aggregator.project_summary(df_master, p.get("project_id", ""))
        if s["has_data"]:
            n_with_data += 1
            revenue += s["revenue"]
            expenses += s["expenses"]
    profit = revenue - expenses
    profit_pct = (profit / revenue * 100) if revenue else 0.0
    n_active = n_with_data

    sec("סקירת פורטפוליו", meta="סיכום כל הפרויקטים במערכת")
    kpis = [
        kpi_block("הכנסות", _fmt_money(revenue), accent="green", icon="ti-trending-up"),
        kpi_block("הוצאות", _fmt_money(expenses), accent="red", icon="ti-trending-down"),
        kpi_block("רווח / הפסד", _fmt_money(profit),
                  accent="green" if profit >= 0 else "red", icon="ti-wallet"),
        kpi_block("% רווחיות", f"{profit_pct:.1f}%",
                  accent="green" if profit >= 0 else "red", icon="ti-percentage"),
        kpi_block("פרויקטים עם נתונים", f"{n_active}", accent="blue",
                  icon="ti-building-community"),
    ]
    render_kpi_group(kpis, "מבט-על חברה", group_icon="ti-chart-bar")


def _clean_text(v) -> str:
    """מנקה NaN/None/ריק → ''. pandas NaN הוא float שמחזיר truthy ב-`or`."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _render_project_card(proj: dict, df_master: pd.DataFrame) -> None:
    """כרטיס יחיד - שם/לקוח/סטטוס/KPIs/כפתור."""
    project_id = proj.get("project_id", "")
    project_name = _clean_text(proj.get("project_name")) or project_id
    client = _clean_text(proj.get("client_name")) or _clean_text(proj.get("notes")) or "—"
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
          <span style="font-size:11px">הוסף קבצי חודש בתיקיית הפרויקט</span>
        </div>
        """

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

    # כפתור Streamlit (לא ניתן לשים בתוך HTML)
    if st.button("פתח פרויקט ←", key=f"open_{project_id}",
                   use_container_width=True, type="primary"):
        st.session_state["selected_project_id"] = project_id
        st.rerun()
