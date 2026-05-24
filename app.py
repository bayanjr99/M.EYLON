"""מערכת ביקורת פרויקטים — מ. אילון אביב נכסים בע"מ.

ניווט project-centric:
  1. מסך נחיתה = רשימת פרויקטים (כרטיסים עם KPIs)
  2. לחיצה על "פתח פרויקט" → דף ייעודי עם 9 טאבים

הניווט מבוסס על st.session_state["selected_project_id"].
הפעלה: streamlit run app.py (או start.bat / start.sh)
"""
from __future__ import annotations

import logging
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
from ui.components import render_top_bar
from ui.pages.project_detail import render_project_detail
from ui.pages.projects_list import render_projects_list
from ui.styles import LOADING_VEIL, MAIN_CSS


# ═══ PAGE CONFIG ═══════════════════════════════════════════
st.set_page_config(
    page_title='מ. אילון אביב נכסים בע"מ — מערכת ביקורת פרויקטים',
    page_icon="static/meylon_aviv_logo.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ═══ Loading veil + main CSS ═══════════════════════════════
# st.html() — bypasses MarkdownIt; st.markdown silently breaks on large
# <style> blocks and dumps the CSS as visible text.
st.html(LOADING_VEIL)
st.html(MAIN_CSS)


# ═══ DATA LOAD ══════════════════════════════════════════════
@st.cache_data(show_spinner=False, ttl=300)
def _load_master() -> pd.DataFrame:
    """טוען master.parquet. ממוטמן ל-5 דקות."""
    return pipeline.load_master()


@st.cache_data(show_spinner=False, ttl=300)
def _load_projects() -> list[dict]:
    """טוען רשימת פרויקטים מ-projects_registry.xlsx."""
    return pipeline.list_available_projects()


df_master = _load_master()
projects = _load_projects()
has_data = not df_master.empty


# ═══ TOP BAR ════════════════════════════════════════════════
_now = datetime.now().strftime("%d/%m/%Y %H:%M")
selected = st.session_state.get("selected_project_id")
if selected:
    proj_name = next((p["project_name"] for p in projects
                      if p.get("project_id") == selected), selected)
    _meta = f'{_now} · פרויקט פעיל: {proj_name}'
    _status, _status_txt = "ok", "מצב פרויקט"
elif has_data:
    _meta = f'{_now} · {len(projects)} פרויקטים · {len(df_master):,} תנועות במאסטר'
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
    logo_path="static/meylon_aviv_logo.png",
)


# ═══ ROUTER ═════════════════════════════════════════════════
selected_project_id = st.session_state.get("selected_project_id")

if selected_project_id:
    # מסך פרויקט בודד
    project_meta = next(
        (p for p in projects if p.get("project_id") == selected_project_id),
        None,
    )
    if project_meta is None:
        st.error(f"פרויקט '{selected_project_id}' לא נמצא ברגיסטרי.")
        if st.button("← חזרה לרשימה"):
            st.session_state.pop("selected_project_id", None)
            st.rerun()
    else:
        render_project_detail(df_master, project_meta)
else:
    # מסך נחיתה — רשימת פרויקטים
    render_projects_list(df_master, projects)


# ═══ FOOTER ═════════════════════════════════════════════════
st.markdown("---")
_footer_left = "מ. אילון אביב נכסים בע\"מ · מערכת ביקורת פרויקטים"
_footer_right = f"{len(df_master):,} שורות במאסטר · {datetime.now().strftime('%d/%m/%Y %H:%M')}"
st.markdown(
    f'<div style="display:flex;justify-content:space-between;font-size:11px;color:#94A3B8;'
    f'padding:8px 0">'
    f'<span>{_footer_left}</span>'
    f'<span>{_footer_right}</span>'
    f'</div>',
    unsafe_allow_html=True,
)
