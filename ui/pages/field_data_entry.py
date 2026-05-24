"""טאב 'עדכון נתוני שטח' - הזנה ידנית של 5 סוגי יומנים תפעוליים.

המטרה: להחליף עדכון אקסל ידני בהזנה ישירה במערכת. הנתונים נשמרים
ב-SQLite ומופיעים מיידית בטאבים האחרים של דף הפרויקט.
"""
from __future__ import annotations

from datetime import date as date_cls

import pandas as pd
import streamlit as st

from core import control_db
from ui.components import ins, sec


# ── Column config helpers ─────────────────────────────────────
def _column_config(table: str) -> dict:
    """בונה column_config ל-st.data_editor לפי TABLES metadata."""
    meta = control_db.TABLES[table]
    cfg = {"id": st.column_config.NumberColumn("ID", disabled=True, width="small")}
    for col, label, kind in meta["user_columns"]:
        required = col in meta["required"]
        if kind == "date":
            cfg[col] = st.column_config.DateColumn(
                label + (" *" if required else ""),
                required=required,
                format="DD/MM/YYYY",
            )
        elif kind == "int":
            cfg[col] = st.column_config.NumberColumn(
                label + (" *" if required else ""),
                required=required, step=1, format="%d",
            )
        elif kind == "float":
            cfg[col] = st.column_config.NumberColumn(
                label + (" *" if required else ""),
                required=required, step=0.5, format="%.2f",
            )
        else:
            cfg[col] = st.column_config.TextColumn(
                label + (" *" if required else ""),
                required=required,
            )
    # Hide bookkeeping columns
    for hidden in ("project_id", "month", "created_at", "updated_at", "source"):
        cfg[hidden] = None
    return cfg


def _editor_state_key(table: str, project_id: str) -> str:
    """state key ל-st.data_editor key + לזיכרון original_ids."""
    return f"editor_{table}_{project_id}"


def _render_sub_tab(table: str, project_id: str, month_filter: str | None,
                    license_filter: int | None) -> None:
    """תת-טאב יחיד עם data_editor + שמירה + פילטרים."""
    meta = control_db.TABLES[table]
    rows = control_db.list_rows(table, project_id, month=month_filter,
                                 license_num=license_filter)
    user_col_names = [c[0] for c in meta["user_columns"]]
    visible_cols = ["id"] + user_col_names

    # Ensure all visible columns exist even when rows is empty
    if rows.empty:
        rows = pd.DataFrame(columns=visible_cols)
    else:
        for c in visible_cols:
            if c not in rows.columns:
                rows[c] = None
        rows = rows[visible_cols]

    # Convert date column to datetime so the DateColumn editor works
    if "date" in rows.columns:
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")

    # Track original ids for delete-detection
    original_ids = {int(i) for i in rows["id"].dropna().tolist()} if not rows.empty else set()
    state_key = _editor_state_key(table, project_id)
    st.session_state[f"{state_key}_original"] = original_ids

    st.caption(f"{len(rows)} שורות. הוסף שורות חדשות, ערוך קיימות, מחק עם 🗑 ב-toolbar.")

    edited = st.data_editor(
        rows,
        column_config=_column_config(table),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=state_key,
    )

    col_save, col_info = st.columns([1, 4])
    with col_save:
        if st.button("💾 שמור", key=f"save_{table}_{project_id}",
                     type="primary", use_container_width=True):
            result = control_db.bulk_save(table, edited, project_id, original_ids)
            if result["errors"]:
                st.error("נמצאו שגיאות:\n" + "\n".join(f"  • {e}" for e in result["errors"]))
            else:
                msg = (f"נוסף: {result['inserted']} · עודכן: {result['updated']} · "
                       f"נמחק: {result['deleted']}")
                st.success(msg)
                # invalidate any cache that depends on this DB so other tabs refresh
                st.cache_data.clear()
                st.rerun()
    with col_info:
        st.caption(f"שדות חובה: {', '.join(meta['required'])}")


# ── Main entry point ──────────────────────────────────────────
def render_field_data_entry(project_meta: dict) -> None:
    """טאב 'עדכון נתוני שטח' - הזנה ידנית של נתונים תפעוליים."""
    project_id = project_meta["project_id"]
    counts = control_db.count_rows(project_id)

    ins("blue", "✍️", "הזנה ישירה למערכת",
        "במקום לעדכן אקסלים, ערוך כאן את הנתונים. כל שינוי נשמר ל-SQLite "
        "ומופיע מיידית בטאבי הפרויקט (עובדים, ספקים, סולר, וכו').")

    # ── פילטרים גלובליים לכל התתי-טאבים ──
    sec("פילטרים")
    col_m, col_l = st.columns([1, 1])
    with col_m:
        month_filter = st.text_input(
            "סנן לפי חודש (MM-YYYY) - השאר ריק לכל החודשים",
            key=f"fdf_month_{project_id}",
        ).strip() or None
    with col_l:
        license_str = st.text_input(
            "סנן לפי מספר רישוי - השאר ריק לכל הכלים",
            key=f"fdf_license_{project_id}",
        ).strip()
        try:
            license_filter = int(license_str) if license_str else None
        except ValueError:
            st.warning(f"מספר רישוי לא תקין: {license_str}")
            license_filter = None

    # ── 5 תתי-טאבים ──
    tab_labels = [
        f"⛽ {control_db.TABLES['fuel_logs']['label']} ({counts['fuel_logs']})",
        f"🚜 {control_db.TABLES['equipment_work_logs']['label']} ({counts['equipment_work_logs']})",
        f"👷 {control_db.TABLES['employee_work_logs']['label']} ({counts['employee_work_logs']})",
        f"🏢 {control_db.TABLES['contractor_work_logs']['label']} ({counts['contractor_work_logs']})",
        f"🔧 {control_db.TABLES['maintenance_logs']['label']} ({counts['maintenance_logs']})",
    ]
    sub_tabs = st.tabs(tab_labels)
    tables_in_order = ["fuel_logs", "equipment_work_logs", "employee_work_logs",
                        "contractor_work_logs", "maintenance_logs"]
    for sub_tab, table in zip(sub_tabs, tables_in_order):
        with sub_tab:
            _render_sub_tab(table, project_id, month_filter, license_filter)
