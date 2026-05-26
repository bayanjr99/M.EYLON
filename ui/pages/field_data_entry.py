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
from ui.formatters import display_dataframe


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

    st.caption(f"{len(rows)} שורות. הוסף שורות חדשות, ערוך קיימות, מחק עם 🗑 בסרגל הכלים.")

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

    # ── 6 תתי-טאבים (5 יומנים + ניהול כלים) ──
    tools_count = len(control_db.list_tools())
    tab_labels = [
        f"⛽ {control_db.TABLES['fuel_logs']['label']} ({counts['fuel_logs']})",
        f"🚜 {control_db.TABLES['equipment_work_logs']['label']} ({counts['equipment_work_logs']})",
        f"👷 {control_db.TABLES['employee_work_logs']['label']} ({counts['employee_work_logs']})",
        f"🏢 {control_db.TABLES['contractor_work_logs']['label']} ({counts['contractor_work_logs']})",
        f"🔧 {control_db.TABLES['maintenance_logs']['label']} ({counts['maintenance_logs']})",
        f"🔩 ניהול כלים ({tools_count})",
    ]
    sub_tabs = st.tabs(tab_labels)
    tables_in_order = ["fuel_logs", "equipment_work_logs", "employee_work_logs",
                        "contractor_work_logs", "maintenance_logs"]
    # First 5: standard data_editor sub-tabs
    for sub_tab, table in zip(sub_tabs[:5], tables_in_order):
        with sub_tab:
            # Special: fuel_logs gets a quick-add form at top
            if table == "fuel_logs":
                _render_fuel_quick_form(project_id)
                st.markdown("---")
            _render_sub_tab(table, project_id, month_filter, license_filter)

    # 6th: tools management
    with sub_tabs[5]:
        _render_tools_management()


# ── Tools management sub-tab ─────────────────────────────────
def _auto_derive_tools_from_data() -> pd.DataFrame:
    """סורק את כל הנתונים הקיימים (master + fuel_invoices) ומחזיר
    DataFrame של כלים שראינו אבל לא נמצאים ב-tools registry.

    מקורות: solar, hours, fuel_invoices.
    מחזיר: DataFrame עם license_num (int), tool_name (str), n_seen (int).
    """
    from pipeline import load_master, load_fuel_invoices_data

    candidates: dict[int, dict] = {}

    def _add(license_num, tool_name, source):
        try:
            lic = int(license_num)
        except (TypeError, ValueError):
            return
        if lic <= 0:
            return
        name = str(tool_name or "").strip() if tool_name and not pd.isna(tool_name) else ""
        if lic not in candidates:
            candidates[lic] = {"license_num": lic, "tool_name": name,
                                "sources": set(), "n_seen": 0}
        candidates[lic]["sources"].add(source)
        candidates[lic]["n_seen"] += 1
        # שמור על השם הראשון שמצאנו (לא ריק)
        if not candidates[lic]["tool_name"] and name:
            candidates[lic]["tool_name"] = name

    # מאסטר: solar + hours
    try:
        master = load_master()
        if not master.empty and "license_num" in master.columns:
            for src_name in ("solar", "hours"):
                rows = master[master["source"] == src_name] if "source" in master.columns else pd.DataFrame()
                if rows.empty:
                    continue
                for _, r in rows[["license_num", "tool_name"]].dropna(subset=["license_num"]).drop_duplicates().iterrows():
                    _add(r.get("license_num"), r.get("tool_name"), src_name)
    except Exception:
        pass

    # fuel_invoices
    try:
        inv = load_fuel_invoices_data()
        if not inv.empty:
            for col in ("license_num", "license", "vehicle_license"):
                if col in inv.columns:
                    for _, r in inv[[col]].dropna().drop_duplicates().iterrows():
                        _add(r[col], "", "fuel_invoices")
                    break
    except Exception:
        pass

    if not candidates:
        return pd.DataFrame(columns=["license_num", "tool_name", "n_seen", "sources"])

    out = pd.DataFrame(list(candidates.values()))
    out["sources"] = out["sources"].apply(lambda s: ", ".join(sorted(s)))
    out = out.sort_values("n_seen", ascending=False).reset_index(drop=True)

    # סנן כלים שכבר ב-control_db
    existing = control_db.list_tools()
    if not existing.empty and "license_num" in existing.columns:
        existing_lics = set(existing["license_num"].dropna().astype(int).tolist())
        out = out[~out["license_num"].isin(existing_lics)]

    return out


def _render_tools_management() -> None:
    """ניהול רשימת כלים: הוספה / מחיקה / עדכון. Fleet-wide."""
    ins("blue", "🔩", "ניהול רשימת כלים",
        "כלים שמוזנים כאן זמינים לכל הפרויקטים. הם ממוזגים עם "
        "קובץ רשימת הכלים הקיים (הזנה ידנית גוברת).")

    # ── רשימה + מחיקה ──
    sec("רשימת כלים", meta="לחץ Delete על שורה למחיקה")
    tools = control_db.list_tools()
    if tools.empty:
        st.caption("אין כלים שהוזנו ידנית. השתמש בטופס 'הוסף כלי חדש' למטה, "
                   "או הפק רשימה אוטומטית מהנתונים הקיימים.")

        # ── הפקה אוטומטית מהנתונים ──
        auto = _auto_derive_tools_from_data()
        if not auto.empty:
            sec("🔍 כלים שזוהו בנתונים", meta=f"{len(auto)} כלים אפשריים")
            preview = auto.copy()
            preview.columns = ["מס' רישוי", "שם / דגם", "מספר הופעות", "מקורות"]
            display_dataframe(preview)
            if st.button(f"➕ הוסף את כל {len(auto)} הכלים לרשימה",
                           type="primary", use_container_width=True,
                           key="auto_add_tools"):
                added = 0
                errors = 0
                for _, r in auto.iterrows():
                    ok, _ = control_db.add_tool(
                        license_num=int(r["license_num"]),
                        tool_name=str(r["tool_name"] or "כלי לא ידוע"),
                        tool_type="",
                        owner="",
                        norm_low=None,
                        norm_high=None,
                        notes=f"נוצר אוטומטית ממקורות: {r['sources']}",
                        internal_num="",
                    )
                    if ok:
                        added += 1
                    else:
                        errors += 1
                if added:
                    st.success(f"✅ נוספו {added} כלים. ערוך כל כלי כדי "
                                "להוסיף סוג, תקן עליון/תחתון, וכו'.")
                if errors:
                    st.warning(f"⚠️ {errors} כלים לא נוספו (אולי קיימים כבר).")
                st.cache_data.clear()
                st.rerun()
    else:
        # סיכום קצר לפי קבוצה
        if "equipment_group" in tools.columns:
            grp_summary = tools.groupby("equipment_group").size().reset_index(name="כמות")
            grp_summary.columns = ["קבוצת כלי", "כמות"]
            cA, cB = st.columns([2, 3])
            with cA:
                display_dataframe(grp_summary, use_container_width=True, hide_index=True)
            with cB:
                st.caption(f"סה\"כ {len(tools)} כלים במערכת. כלים נוספים מקובץ רשימת הכלים מוצגים למטה.")

        show_cols = ["license_num", "internal_num", "tool_name", "tool_type",
                      "equipment_group", "fuel_type", "ownership", "status",
                      "owner", "norm_low", "norm_high", "notes"]
        show_cols = [c for c in show_cols if c in tools.columns]
        disp = tools[show_cols].copy()
        heb = {"license_num": "מס' רישוי", "internal_num": "מס' פנימי",
               "tool_name": "שם / דגם", "tool_type": "סוג",
               "equipment_group": "קבוצה", "fuel_type": "סוג דלק",
               "ownership": "בעלות", "status": "סטטוס",
               "owner": "בעלים שם", "norm_low": "תקן ת'", "norm_high": "תקן ע'",
               "notes": "הערות"}
        disp.columns = [heb.get(c, c) for c in show_cols]
        display_dataframe(disp, use_container_width=True, hide_index=True)

        # Delete by license_num
        c_d1, c_d2 = st.columns([1, 3])
        with c_d1:
            del_lic_str = st.text_input("מחק לפי רישוי", key="del_tool_lic")
        with c_d2:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            try:
                del_lic_int = int((del_lic_str or "").strip()) if del_lic_str else 0
            except (TypeError, ValueError):
                del_lic_int = 0
            if st.button("🗑 מחק כלי", key="del_tool_btn",
                         disabled=del_lic_int <= 0, type="secondary"):
                if control_db.delete_tool_by_license(del_lic_int):
                    st.success(f"כלי {del_lic_int} נמחק")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"כלי {del_lic_int} לא נמצא במערכת (ייתכן שהוא בקובץ רשימת הכלים בלבד)")

    # ── מוצג גם: כלים מקובץ רשימת הכלים (לקריאה בלבד) ──
    from pipeline import _load_tools_registry, TOOLS_REGISTRY
    merged = _load_tools_registry()
    n_xlsx = (len(merged) - len(tools)) if not tools.empty else len(merged)
    if n_xlsx > 0:
        with st.expander(f"📄 כלים מקובץ רשימת הכלים ({n_xlsx}) - לקריאה בלבד"):
            st.caption(f"מקור: {TOOLS_REGISTRY.name}. כדי לערוך - הוסף את אותו מספר רישוי במערכת.")
            xlsx_only = merged[~merged["license_num"].isin(
                set(tools["license_num"].dropna().astype(int)) if not tools.empty else set()
            )]
            cols = [c for c in ["license_num", "tool_name", "tool_type", "norm_low", "norm_high"]
                    if c in xlsx_only.columns]
            heb_xlsx = {
                "license_num": "מס' רישוי",
                "tool_name":   "שם / דגם",
                "tool_type":   "סוג",
                "norm_low":    "תקן תחתון",
                "norm_high":   "תקן עליון",
            }
            disp_xlsx = xlsx_only[cols].copy()
            disp_xlsx.columns = [heb_xlsx.get(c, c) for c in cols]
            display_dataframe(disp_xlsx, use_container_width=True, hide_index=True)

    # ── טופס הוספה (מתחת לרשימה, מקופל כברירת מחדל) ──
    with st.expander("➕ הוסף כלי חדש", expanded=False):
        with st.form("add_tool_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                new_lic_str = st.text_input("מספר רישוי *")
            with c2:
                new_name = st.text_input("שם / דגם *")
            with c3:
                new_internal = st.text_input("מספר פנימי", help="מספר שלך / מקובץ עליו תזכור")
            c4, c5, c6, c7 = st.columns(4)
            with c4:
                new_group = st.selectbox("קבוצת כלי", control_db.EQUIPMENT_GROUPS,
                                           help="צמ\"ה / רכב / משאית / חשמלי")
            with c5:
                new_fuel = st.selectbox("סוג דלק", control_db.FUEL_TYPES,
                                          help="לזיהוי שיוך תדלוקים")
            with c6:
                new_owner_kind = st.selectbox("סוג בעלות", control_db.OWNERSHIPS)
            with c7:
                new_status = st.selectbox("סטטוס", control_db.EQUIPMENT_STATUSES)
            c8, c9, c10 = st.columns(3)
            with c8:
                new_type = st.text_input("סוג כלי (תיאור חופשי)")
            with c9:
                new_owner = st.text_input("בעלים שם",
                                           help="בעלים אילון / אבו גאנם / וכו'")
            with c10:
                new_notes = st.text_input("הערות")
            c11, c12 = st.columns(2)
            with c11:
                new_nl = st.number_input("תקן תחתון (ל'/ש') - 0 אם לא ידוע",
                                          min_value=0.0, step=0.5, value=0.0)
            with c12:
                new_nh = st.number_input("תקן עליון (ל'/ש') - 0 אם לא ידוע",
                                          min_value=0.0, step=0.5, value=0.0)
            submitted = st.form_submit_button("➕ הוסף כלי", type="primary",
                                               use_container_width=True)
            if submitted:
                try:
                    lic_int = int((new_lic_str or "").strip())
                except (TypeError, ValueError):
                    lic_int = 0
                ok, msg = control_db.add_tool(
                    license_num=lic_int,
                    tool_name=new_name or "",
                    tool_type=new_type or "",
                    owner=new_owner or "",
                    norm_low=float(new_nl) if new_nl > 0 else None,
                    norm_high=float(new_nh) if new_nh > 0 else None,
                    notes=new_notes or "",
                    internal_num=new_internal or "",
                    equipment_group=new_group,
                    fuel_type=new_fuel,
                    ownership=new_owner_kind,
                    status=new_status,
                )
                if ok:
                    st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(msg)


# ── Quick fuel entry form ────────────────────────────────────
def _render_fuel_quick_form(project_id: str) -> None:
    """טופס מהיר להוספת תדלוק יחיד - נוח כש יש רק תדלוק אחד להזין."""
    from pipeline import _load_tools_registry
    tools = _load_tools_registry()
    tool_options: dict[str, int | None] = {"— בחר כלי —": None}
    if not tools.empty:
        for _, r in tools.iterrows():
            lic = r.get("license_num")
            name = r.get("tool_name", "")
            if pd.notna(lic):
                tool_options[f"{int(lic)} · {name}"] = int(lic)

    with st.expander("🆕 הוספת תדלוק מהירה", expanded=False):
        with st.form("quick_fuel_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                pick = st.selectbox("כלי", list(tool_options.keys()),
                                     key="qf_tool")
                qf_date = st.date_input("תאריך", value=date_cls.today(), key="qf_date")
                qf_driver = st.text_input("נהג / מפעיל", key="qf_driver")
            with c2:
                qf_supplier = st.text_input("ספק", key="qf_supplier")
                qf_invoice = st.text_input("מס' חשבונית", key="qf_invoice")
                qf_liters = st.number_input("ליטרים *", min_value=0.0, step=1.0,
                                              key="qf_liters")
            c3, c4 = st.columns(2)
            with c3:
                qf_price = st.number_input("₪ לליטר (אופציונלי)", min_value=0.0, step=0.1,
                                             key="qf_price")
            with c4:
                qf_notes = st.text_input("הערות", key="qf_notes")

            submitted = st.form_submit_button("⛽ שמור תדלוק", type="primary",
                                                use_container_width=True)
            if submitted:
                lic = tool_options.get(pick)
                if lic is None:
                    st.error("בחר כלי מהרשימה.")
                elif qf_liters <= 0:
                    st.error("הזן ליטרים גדולים מ-0.")
                else:
                    tool_name = pick.split("·", 1)[1].strip() if "·" in pick else ""
                    total = qf_liters * qf_price if qf_price > 0 else None
                    row_df = pd.DataFrame([{
                        "id": None,
                        "date": qf_date.strftime("%Y-%m-%d"),
                        "tool_name": tool_name,
                        "license_num": lic,
                        "driver": qf_driver or None,
                        "supplier": qf_supplier or None,
                        "invoice_num": qf_invoice or None,
                        "liters": qf_liters,
                        "price_per_liter": qf_price if qf_price > 0 else None,
                        "total_cost": total,
                        "notes": qf_notes or None,
                    }])
                    result = control_db.bulk_save("fuel_logs", row_df, project_id)
                    if result["errors"]:
                        st.error("\n".join(result["errors"]))
                    else:
                        st.success(f"תדלוק נשמר: {lic} · {qf_liters:.0f} ל' "
                                   + (f"· ₪{total:,.0f}" if total else ""))
                        st.cache_data.clear()
                        st.rerun()
