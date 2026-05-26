"""מסך פירוט (Drill-Down) — מציג תנועות, KPIs, גרף וייצוא לישות אחת.

הגרסה הראשונה תומכת ב-4 ישויות:
    - supplier  (ספק)         — detail_value הוא שם הספק (str)
    - customer  (לקוח)        — detail_value הוא שם הלקוח (str)
    - tool      (כלי)         — detail_value הוא license_num (int)
    - month     (חודש)        — detail_value הוא MM-YYYY (str)

הראוטר נקרא מ-render_project_detail ב-project_detail.py. אם
st.session_state["detail_type"] מוגדר → render_detail_view לוקח
שליטה ומציג מסך פירוט במקום הטאבים הרגילים.

פתיחת פירוט (בכל מקום בטאבים):
    st.session_state["detail_type"]  = "supplier"
    st.session_state["detail_value"] = "נ. ג'אן"
    st.session_state["return_view"]  = "finance/suppliers"  # אופציונלי
    st.rerun()
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from ui.components import breadcrumb, empty_state, ins, sec
from ui.formatters import (
    build_column_config, clean_dataframe_for_display, display_dataframe,
    format_currency, format_decimal, format_number, format_percent,
)


# ── עזרים משותפים ──────────────────────────────────────────

def _back_button(project_id: str) -> None:
    """כפתור 'חזרה' שמנקה את הפירוט ומחזיר למסך הקודם."""
    if st.button("← חזרה", key=f"detail_back_{project_id}",
                   use_container_width=False):
        st.session_state.pop("detail_type", None)
        st.session_state.pop("detail_value", None)
        st.session_state.pop("return_view", None)
        st.rerun()


def _excel_download_button(tx_df: pd.DataFrame, file_basename: str,
                            key_suffix: str, sheet_name: str = "פירוט") -> None:
    """כפתור הורדת DataFrame כ-xlsx (פורמט #,##0 על סכומים)."""
    if tx_df.empty:
        return
    buf = BytesIO()
    try:
        engine = "xlsxwriter"
        import xlsxwriter  # noqa: F401
    except ImportError:
        engine = "openpyxl"
    with pd.ExcelWriter(buf, engine=engine) as writer:
        sheet = sheet_name[:31] or "פירוט"
        tx_df.to_excel(writer, sheet_name=sheet, index=False)
        if engine == "xlsxwriter":
            wb = writer.book
            ws = writer.sheets[sheet]
            money_fmt = wb.add_format({"num_format": "#,##0"})
            money_keywords = ("סכום", "סה\"כ", "₪", "ליטרים", "שעות",
                              "חובה", "זכות", "נטו", "יתרה", "עלות",
                              "מחיר", "הכנסות", "הוצאות")
            for col_idx, col_name in enumerate(tx_df.columns):
                if any(k in str(col_name) for k in money_keywords):
                    ws.set_column(col_idx, col_idx, 16, money_fmt)
                else:
                    ws.set_column(col_idx, col_idx, 18)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    st.download_button(
        "📥 ייצוא לאקסל",
        data=buf.getvalue(),
        file_name=f"{file_basename}_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"detail_dl_{key_suffix}",
        use_container_width=False,
    )


def _monthly_chart(tx_df: pd.DataFrame, amount_col: str = "amount",
                     title: str = "תנועה חודשית") -> None:
    """גרף בר לפי חודש על עמודת סכום נתונה.

    משתמש ב-st.bar_chart (פשוט, RTL-friendly, ללא תלות ב-Plotly).
    """
    if tx_df.empty or "month" not in tx_df.columns:
        return
    if amount_col not in tx_df.columns:
        return
    monthly = tx_df.groupby("month")[amount_col].sum().abs()
    if monthly.empty:
        return
    # מסדר חודשים לפי תאריך אמיתי לא ע"פ מחרוזת
    def _month_sort_key(m):
        try:
            return pd.to_datetime(m, format="%m-%Y")
        except Exception:
            return pd.Timestamp.min
    monthly = monthly.sort_index(key=lambda idx: idx.map(_month_sort_key))

    sec(title)
    st.bar_chart(monthly)


def _kpi_row(tx_df: pd.DataFrame, amount_col: str = "amount") -> None:
    """KPIs בסיסיים: סה\"כ / תנועות / חודשים / ממוצע חודשי."""
    n = len(tx_df)
    total = float(tx_df[amount_col].abs().sum()) \
        if amount_col in tx_df.columns and n else 0
    n_months = int(tx_df["month"].nunique()) \
        if "month" in tx_df.columns and n else 0
    avg_monthly = total / n_months if n_months else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה\"כ", format_currency(total))
    c2.metric("תנועות", format_number(n))
    c3.metric("חודשים פעילים", format_number(n_months))
    c4.metric("ממוצע חודשי", format_currency(avg_monthly) if n_months else "—")


_TX_COL_HEB = {
    "date":          "תאריך",
    "month":         "חודש",
    "account_num":   "מס' חשבון",
    "account_name":  "שם חשבון",
    "supplier":      "ספק / לקוח",
    "description":   "פרטים",
    "debit":         "חובה",
    "credit":        "זכות",
    "amount":        "סכום",
    "net_amount":    "נטו (₪)",
    "main_category": "קטגוריה",
    "sub_category":  "תת-קטגוריה",
    "license_num":   "מס' רישוי",
    "tool_name":     "שם כלי",
    "liters":        "ליטרים",
    "work_hours":    "שעות עבודה",
    "source":        "מקור",
}

_SOURCE_HE = {
    "chashbashevet":   "כרטיס הנהלה",
    "solar":           "תדלוקים",
    "hours":           "שעות עבודה",
    "manual":          "ידני",
    "balance":         "מאזן בוחן",
    "fuel_invoices":   "חשבוניות דלק",
    "site_tracking":   "יומן שטח",
}


def _render_tx_table(tx_df: pd.DataFrame, show_cols: list[str] | None = None) -> None:
    """טבלת תנועות אחידה — תרגום כותרות, ניקוי NaN, פורמט מספרים."""
    if tx_df.empty:
        st.caption("אין תנועות להצגה.")
        return
    default_cols = ["date", "month", "account_num", "account_name",
                     "supplier", "description", "amount", "source"]
    cols = show_cols or [c for c in default_cols if c in tx_df.columns]
    disp = tx_df[cols].copy()
    if "date" in cols:
        disp = disp.sort_values("date", ascending=False)
    # תרגום source לעברית
    if "source" in disp.columns:
        disp["source"] = disp["source"].map(_SOURCE_HE).fillna(disp["source"])
    # תרגום כותרות
    disp.columns = [_TX_COL_HEB.get(c, c) for c in cols]
    display_dataframe(disp)


def _empty_detail(detail_type_he: str) -> None:
    empty_state(
        icon="ti-database-off",
        title=f"לא נמצאו נתונים עבור הבחירה הזו",
        body_html=f"לא קיימות תנועות ל-{detail_type_he} שנבחר.",
    )


# ── Launcher — selectbox + 🔍 פתח פירוט ────────────────────

def drill_launcher(detail_type: str, options: list,
                    label: str = "בחר ערך לפירוט",
                    key_suffix: str = "") -> None:
    """ממקם selectbox + כפתור '🔍 פתח פירוט' אחרי טבלת סיכום.

    detail_type אחד מ-{supplier, customer, tool, month}.
    options: רשימת ערכים אפשריים (שמות / license_nums / חודשים).

    בלחיצה על הכפתור — שם ב-session_state את detail_type/value
    וקורא ל-st.rerun.
    """
    if not options:
        return
    safe_key = f"drill_{detail_type}_{key_suffix}".strip("_")
    cc1, cc2 = st.columns([3, 1])
    with cc1:
        pick = st.selectbox(
            label, ["— בחר —"] + [str(o) for o in options],
            key=f"{safe_key}_sel",
        )
    with cc2:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("🔍 פתח פירוט", key=f"{safe_key}_btn",
                       use_container_width=True,
                       disabled=(pick == "— בחר —")):
            st.session_state["detail_type"] = detail_type
            # tool → int; שאר → str
            if detail_type == "tool":
                try:
                    st.session_state["detail_value"] = int(pick)
                except (TypeError, ValueError):
                    st.session_state["detail_value"] = pick
            else:
                st.session_state["detail_value"] = pick
            st.rerun()


# ── הראוטר הראשי ───────────────────────────────────────────

def render_detail_view(df_master: pd.DataFrame, project_meta: dict) -> bool:
    """אם detail_type מוגדר ב-session_state, מציג מסך פירוט ומחזיר True.

    Returns:
        True אם הוצג מסך פירוט (וצריך לא להמשיך לטאבים הרגילים).
        False אם אין פירוט פעיל.
    """
    dt = st.session_state.get("detail_type")
    dv = st.session_state.get("detail_value")
    if not dt or dv is None:
        return False

    project_id = project_meta["project_id"]

    # סינון ל-project_id בלבד
    if df_master.empty or "project_id" not in df_master.columns:
        df = df_master
    else:
        df = df_master[df_master["project_id"] == project_id]

    if dt == "supplier":
        _render_supplier_detail(df, project_meta, str(dv))
    elif dt == "customer":
        _render_customer_detail(df, project_meta, str(dv))
    elif dt == "tool":
        try:
            lic = int(dv)
        except (TypeError, ValueError):
            lic = None
        if lic is None:
            empty_state(icon="ti-alert", title="מספר רישוי לא תקין",
                          body_html=f"ערך לא צפוי: {dv!r}")
            _back_button(project_id)
        else:
            _render_tool_detail(df, project_meta, lic)
    elif dt == "month":
        _render_month_detail(df, project_meta, str(dv))
    else:
        empty_state(icon="ti-alert",
                       title=f"סוג פירוט לא נתמך: {dt}",
                       body_html="חזור למסך הקודם ונסה שוב.")
        _back_button(project_id)
    return True


# ── 1. פירוט ספק ──────────────────────────────────────────

def _render_supplier_detail(df: pd.DataFrame, project_meta: dict,
                              supplier: str) -> None:
    project_id = project_meta["project_id"]
    project_name = project_meta.get("project_name", project_id)

    _back_button(project_id)
    breadcrumb("פרויקט", project_name, "ספק", supplier)
    sec(f"🏪 פירוט ספק — {supplier}")

    if df.empty or "supplier" not in df.columns:
        _empty_detail(f"ספק '{supplier}'")
        return
    tx = df[df["supplier"].fillna("").astype(str) == supplier]
    if tx.empty:
        _empty_detail(f"ספק '{supplier}'")
        return

    _kpi_row(tx)
    _monthly_chart(tx, amount_col="amount", title="תנועה חודשית של הספק")

    sec("פירוט תנועות")
    _render_tx_table(tx)
    _excel_download_button(
        clean_dataframe_for_display(
            tx[[c for c in ["date", "month", "account_num", "account_name",
                              "supplier", "description", "amount", "source"]
                  if c in tx.columns]].rename(columns=_TX_COL_HEB),
        ),
        file_basename=f"supplier_{supplier[:30]}_{project_id}",
        key_suffix=f"supplier_{supplier[:20]}",
        sheet_name=f"ספק {supplier[:20]}",
    )


# ── 2. פירוט לקוח ─────────────────────────────────────────

def _render_customer_detail(df: pd.DataFrame, project_meta: dict,
                              customer: str) -> None:
    """פירוט לקוח = תנועות הכנסה ששייכות לאותו 'supplier' (השם בכרטיס)."""
    from core.chashbashevet_loader import real_income_mask
    project_id = project_meta["project_id"]
    project_name = project_meta.get("project_name", project_id)

    _back_button(project_id)
    breadcrumb("פרויקט", project_name, "לקוח", customer)
    sec(f"💰 פירוט לקוח — {customer}")

    if df.empty:
        _empty_detail(f"לקוח '{customer}'")
        return

    chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df
    if chash.empty:
        _empty_detail(f"לקוח '{customer}'")
        return
    income = chash[real_income_mask(chash)]
    if income.empty or "supplier" not in income.columns:
        _empty_detail(f"לקוח '{customer}'")
        return
    tx = income[income["supplier"].fillna("").astype(str) == customer]
    if tx.empty:
        _empty_detail(f"לקוח '{customer}'")
        return

    # שורות הכנסה ב-master יכולות להיות עם amount שלילי (אחרי inversion).
    # להצגה נוחה — נשתמש ב-abs.
    tx_disp = tx.copy()
    tx_disp["amount"] = tx_disp["amount"].abs()
    _kpi_row(tx_disp)
    _monthly_chart(tx_disp, amount_col="amount", title="הכנסות חודשיות מהלקוח")

    sec("פירוט חשבוניות")
    _render_tx_table(tx_disp)
    _excel_download_button(
        clean_dataframe_for_display(
            tx_disp[[c for c in ["date", "month", "account_num", "account_name",
                                    "supplier", "description", "amount", "source"]
                       if c in tx_disp.columns]].rename(columns=_TX_COL_HEB),
        ),
        file_basename=f"customer_{customer[:30]}_{project_id}",
        key_suffix=f"customer_{customer[:20]}",
        sheet_name=f"לקוח {customer[:20]}",
    )


# ── 3. פירוט כלי ──────────────────────────────────────────

def _render_tool_detail(df: pd.DataFrame, project_meta: dict,
                          license_num: int) -> None:
    project_id = project_meta["project_id"]
    project_name = project_meta.get("project_name", project_id)

    # שם הכלי לכותרת
    from pipeline import _load_tools_registry
    tools_reg = _load_tools_registry()
    tool_name = ""
    if not tools_reg.empty and license_num in tools_reg["license_num"].values:
        tool_name = str(tools_reg[tools_reg["license_num"] == license_num]
                         .iloc[0].get("tool_name", "") or "")

    title_label = f"{license_num}" + (f" · {tool_name}" if tool_name else "")
    _back_button(project_id)
    breadcrumb("פרויקט", project_name, "כלי", title_label)
    sec(f"🚜 פירוט כלי — {title_label}")

    if df.empty or "license_num" not in df.columns:
        _empty_detail(f"כלי {title_label}")
        return

    # תנועות שמופיעות עם license_num תואם (solar/hours)
    direct = df[df["license_num"] == license_num] \
        if "license_num" in df.columns else df.iloc[0:0]

    # בנוסף — שיוכים ידניים של תנועות chashbashevet לאותו כלי
    from core import fuel_assignments
    assignments = fuel_assignments.fuel_cost_per_license(project_id, df)
    has_manual = (not assignments.empty
                  and license_num in assignments["license_num"].values)
    if has_manual:
        # שולפים את התנועות עצמן (לא רק את הסיכום)
        all_assignments = fuel_assignments._load_all(project_id)  # noqa: SLF001
        chash = df[df["source"] == "chashbashevet"] if "source" in df.columns else df.iloc[0:0]
        manual_rows_idx = []
        for i, r in chash.iterrows():
            h = fuel_assignments.row_hash(
                r.get("date"), r.get("supplier"),
                r.get("amount"), r.get("description"),
            )
            rec = all_assignments.get(h)
            if rec and int(rec.get("license_num", 0)) == license_num:
                manual_rows_idx.append(i)
        manual_tx = chash.loc[manual_rows_idx] if manual_rows_idx else chash.iloc[0:0]
    else:
        manual_tx = df.iloc[0:0]

    # מאחדים את שני המקורות לתצוגה
    all_tx = pd.concat([direct, manual_tx], ignore_index=True, sort=False) \
        if not direct.empty or not manual_tx.empty else df.iloc[0:0]

    if all_tx.empty:
        _empty_detail(f"כלי {title_label}")
        return

    # ── KPIs (משתמשים גם בליטרים ושעות אם יש) ──
    n = len(all_tx)
    total_cost = float(all_tx.get("amount", pd.Series([0])).abs().sum())
    total_liters = float(all_tx["liters"].sum()) \
        if "liters" in all_tx.columns else 0
    total_hours = float(all_tx["work_hours"].sum()) \
        if "work_hours" in all_tx.columns else 0
    n_months = int(all_tx["month"].nunique()) \
        if "month" in all_tx.columns else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה\"כ עלות", format_currency(total_cost))
    c2.metric("ליטרים", format_number(total_liters))
    c3.metric("שעות עבודה", format_decimal(total_hours, decimals=1))
    c4.metric("חודשים פעילים", format_number(n_months))
    if total_hours > 0 and total_liters > 0:
        st.caption(f"ל'/ש' בפועל: {format_decimal(total_liters / total_hours, decimals=2)}")
    if total_hours > 0 and total_cost > 0:
        st.caption(f"₪/שעה: {format_currency(total_cost / total_hours)}")

    _monthly_chart(all_tx, amount_col="amount", title="תנועות חודשיות לכלי")

    sec("פירוט תנועות")
    tool_cols = [c for c in ["date", "month", "source", "supplier",
                                "description", "liters", "work_hours", "amount"]
                  if c in all_tx.columns]
    _render_tx_table(all_tx, show_cols=tool_cols)
    _excel_download_button(
        clean_dataframe_for_display(
            all_tx[tool_cols].rename(columns=_TX_COL_HEB),
        ),
        file_basename=f"tool_{license_num}_{project_id}",
        key_suffix=f"tool_{license_num}",
        sheet_name=f"כלי {license_num}",
    )


# ── 4. פירוט חודש ─────────────────────────────────────────

def _render_month_detail(df: pd.DataFrame, project_meta: dict,
                           month: str) -> None:
    from core.chashbashevet_loader import real_income_mask
    project_id = project_meta["project_id"]
    project_name = project_meta.get("project_name", project_id)

    _back_button(project_id)
    breadcrumb("פרויקט", project_name, "חודש", month)
    sec(f"📅 פירוט חודש — {month}")

    if df.empty or "month" not in df.columns:
        _empty_detail(f"חודש {month}")
        return
    tx = df[df["month"] == month]
    if tx.empty:
        _empty_detail(f"חודש {month}")
        return

    # ── KPIs: הכנסות / הוצאות / רווח לחודש ──
    chash = tx[tx["source"] == "chashbashevet"] if "source" in tx.columns else tx
    if not chash.empty:
        income_mask = real_income_mask(chash)
        revenue = float(-chash[income_mask]["amount"].sum()) \
            if income_mask.any() else 0
        expenses = float(chash[~income_mask].loc[chash["amount"] > 0, "amount"].sum())
    else:
        revenue, expenses = 0, 0
    profit = revenue - expenses
    profit_pct = (profit / revenue * 100) if revenue > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("הכנסות", format_currency(revenue))
    c2.metric("הוצאות", format_currency(expenses))
    c3.metric("רווח / הפסד", format_currency(profit))
    c4.metric("% רווחיות",
                format_percent(profit_pct, decimals=1, already_pct=True)
                if revenue else "—")

    # ── חלוקה לפי קטגוריה (לפי main_category) ──
    if not chash.empty and "main_category" in chash.columns:
        exp = chash[~real_income_mask(chash) & (chash["amount"] > 0)]
        if not exp.empty:
            sec("הוצאות לפי קטגוריה")
            by_cat = exp.groupby("main_category")["amount"].agg(
                ["sum", "count"]).reset_index()
            by_cat.columns = ["קטגוריה", "סכום (₪)", "תנועות"]
            display_dataframe(by_cat.sort_values("סכום (₪)", ascending=False))

    # ── טבלה מלאה ──
    sec("כל התנועות בחודש")
    _render_tx_table(tx)
    _excel_download_button(
        clean_dataframe_for_display(
            tx[[c for c in ["date", "account_num", "account_name", "supplier",
                              "description", "amount", "source"]
                  if c in tx.columns]].rename(columns=_TX_COL_HEB),
        ),
        file_basename=f"month_{month}_{project_id}",
        key_suffix=f"month_{month}",
        sheet_name=f"חודש {month}",
    )
