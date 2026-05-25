"""טאב תקציב מול ביצוע - הזנת תקציב וטבלת השוואה אקטיבית."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import budget_db
from ui.components import ins, sec
from ui.formatters import format_currency, format_percent


CONTRACT_TYPES = {
    "פאושלי": "pausali",
    "לפי כמויות": "per_quantity",
    "לפי שעות": "per_hour",
    "אחר": "other",
}
CONTRACT_TYPE_LABELS = {v: k for k, v in CONTRACT_TYPES.items()}


def _fmt_money(v: float) -> str:
    """פורמט מלא: ₪1,250,000."""
    return format_currency(v)


def render_budget_tab(df: pd.DataFrame, project_meta: dict) -> None:
    """טאב תקציב מול ביצוע."""
    project_id = project_meta["project_id"]
    meta = budget_db.get_metadata(project_id) or {}

    # ── 1. פרטי הפרויקט / חוזה ──
    sec("פרטי פרויקט וחוזה")
    with st.expander("פרטי הפרויקט והחוזה", expanded=not meta):
        with st.form("project_meta_form"):
            c1, c2 = st.columns(2)
            with c1:
                client_name = st.text_input("לקוח", value=meta.get("client_name") or "")
                location = st.text_input("מיקום", value=meta.get("location") or "")
                pm = st.text_input("מנהל פרויקט", value=meta.get("project_manager") or "")
                start_str = meta.get("start_date") or ""
                try:
                    start_val = pd.to_datetime(start_str).date() if start_str else date.today()
                except Exception:
                    start_val = date.today()
                start_date = st.date_input("תאריך התחלה", value=start_val,
                                            format="DD/MM/YYYY")
            with c2:
                end_str = meta.get("expected_end") or ""
                try:
                    end_val = pd.to_datetime(end_str).date() if end_str else None
                except Exception:
                    end_val = None
                expected_end = st.date_input("תאריך סיום צפוי", value=end_val,
                                              format="DD/MM/YYYY")
                ct_label = CONTRACT_TYPE_LABELS.get(meta.get("contract_type") or "", "אחר")
                ct_choice = st.selectbox("סוג חוזה", list(CONTRACT_TYPES.keys()),
                                          index=list(CONTRACT_TYPES.keys()).index(ct_label))
                contract_amount = st.number_input(
                    "סכום חוזה (₪)", min_value=0.0, step=10000.0,
                    value=float(meta.get("contract_amount") or 0),
                )
                notes = st.text_area("הערות חוזה", value=meta.get("contract_notes") or "")
            if st.form_submit_button("💾 שמור פרטי פרויקט", type="primary",
                                       use_container_width=True):
                budget_db.save_metadata(
                    project_id,
                    client_name=client_name,
                    location=location,
                    project_manager=pm,
                    start_date=start_date.strftime("%Y-%m-%d") if start_date else None,
                    expected_end=expected_end.strftime("%Y-%m-%d") if expected_end else None,
                    contract_type=CONTRACT_TYPES.get(ct_choice, "other"),
                    contract_amount=contract_amount,
                    contract_notes=notes,
                )
                st.success("נשמר")
                st.rerun()

    # ── 2. תקציב לפי קטגוריה ──
    sec("תקציב לפי קטגוריה", meta="ערוך וסגור עם 💾 שמור תקציב")
    budget_df = budget_db.get_budget(project_id)

    # Initialize with default categories if empty
    if budget_df.empty:
        budget_df = pd.DataFrame({
            "category": budget_db.DEFAULT_BUDGET_CATEGORIES,
            "budget": [0.0] * len(budget_db.DEFAULT_BUDGET_CATEGORIES),
            "notes": [""] * len(budget_db.DEFAULT_BUDGET_CATEGORIES),
        })

    edited_budget = st.data_editor(
        budget_df,
        column_config={
            "category": st.column_config.TextColumn("קטגוריה", required=True),
            "budget": st.column_config.NumberColumn("תקציב (₪)", min_value=0,
                                                       step=1000.0, format="%.0f"),
            "notes": st.column_config.TextColumn("הערות"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"budget_editor_{project_id}",
    )

    if st.button("💾 שמור תקציב", type="primary", key="save_budget_btn"):
        n = budget_db.save_budget_bulk(project_id, edited_budget)
        st.success(f"נשמרו {n} שורות תקציב")
        st.cache_data.clear()
        st.rerun()

    # ── 3. השוואה: תקציב מול ביצוע ──
    sec("השוואה: תקציב מול ביצוע", meta="חישוב אוטומטי מ-master.parquet")

    # Build actuals dict per category
    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
    exp = chash[chash["amount"] > 0] if "amount" in chash.columns else chash.iloc[0:0]
    income = chash[chash["amount"] < 0] if "amount" in chash.columns else chash.iloc[0:0]
    actuals = {}
    if not exp.empty and "category" in exp.columns:
        actuals = exp.groupby("category")["amount"].sum().to_dict()
    revenue_actual = float(-income["amount"].sum()) if not income.empty else 0.0

    cmp_df = budget_db.compare_budget_vs_actual(project_id, actuals, revenue_actual)
    if cmp_df.empty:
        st.caption("אין נתונים להשוואה (אין תקציב + אין ביצוע).")
        return

    # ── KPI strip: total budget vs total actual ──
    expense_rows = cmp_df[cmp_df["category"] != "הכנסות"]
    total_budget = float(expense_rows["budget"].sum())
    total_actual = float(expense_rows["actual"].sum())
    rev_row = cmp_df[cmp_df["category"] == "הכנסות"]
    rev_budget = float(rev_row["budget"].iloc[0]) if not rev_row.empty else 0
    rev_actual = float(rev_row["actual"].iloc[0]) if not rev_row.empty else 0
    expected_profit = rev_budget - total_budget if rev_budget > 0 else None
    actual_profit = rev_actual - total_actual

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("תקציב הוצאות", _fmt_money(total_budget))
    c2.metric("ביצוע הוצאות", _fmt_money(total_actual),
              delta=f"-{_fmt_money(total_actual - total_budget)}"
              if total_actual > total_budget else _fmt_money(total_budget - total_actual),
              delta_color="inverse")
    c3.metric("רווח צפוי לפי תקציב", _fmt_money(expected_profit) if expected_profit else "—")
    c4.metric("רווח נוכחי", _fmt_money(actual_profit),
              delta_color="normal")

    # ── טבלת השוואה מפורטת ──
    disp = cmp_df.copy()
    disp["budget"] = disp["budget"].apply(_fmt_money)
    disp["actual"] = disp["actual"].apply(_fmt_money)
    disp["variance"] = disp["variance"].apply(_fmt_money)
    disp["util_pct"] = disp["util_pct"].apply(
        lambda v: format_percent(v, already_pct=True) if pd.notna(v) else "—"
    )
    disp.columns = ["קטגוריה", "תקציב", "בפועל", "יתרה", "% ניצול", "סטטוס"]
    st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── התראות ──
    over_budget = cmp_df[(cmp_df["category"] != "הכנסות") &
                          (cmp_df["budget"] > 0) &
                          (cmp_df["actual"] > cmp_df["budget"])]
    if not over_budget.empty:
        ins("red", "⚠️", f"{len(over_budget)} קטגוריות חרגו מהתקציב",
            ", ".join(over_budget["category"].tolist()))
    if rev_budget > 0 and rev_actual < rev_budget * 0.8:
        gap = rev_budget - rev_actual
        ins("amber", "📉", "פיגור משמעותי בהכנסות",
            f"חסרים {_fmt_money(gap)} כדי להגיע ליעד ההכנסות "
            f"({format_percent(rev_actual / rev_budget, decimals=0)} מהיעד).")
