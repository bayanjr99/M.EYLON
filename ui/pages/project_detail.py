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


# ─── Tab 2: הכנסות (חשבוניות-לרמת-פירוט) ────────────────────
import re as _re

_INVOICE_NUM_RE = _re.compile(r"(?:חשבונית|חש\"מ|חש'?\s*מס|אסמכתא)\s*[#:]?\s*(\d{3,})")


def _extract_invoice_num(description: str) -> str:
    """מנסה לחלץ מספר חשבונית מתוך 'פרטים'."""
    if not isinstance(description, str):
        return ""
    m = _INVOICE_NUM_RE.search(description)
    if m:
        return m.group(1)
    # fallback: מספר 4+ ספרות בודד בתחילת/באמצע ה-string
    m = _re.search(r"\b(\d{4,})\b", description)
    return m.group(1) if m else ""


def _tab_income(df: pd.DataFrame) -> None:
    # הכנסות = amount שלילי (חשבונות 927/951/7367 נורמלו לסלילי) או מילות מפתח
    income = df[df["amount"] < 0] if "amount" in df.columns else df.iloc[0:0]
    income_kw = _filter_by_keywords(df, KEYWORD_CATEGORIES["income"])
    income_all = (pd.concat([income, income_kw]).drop_duplicates()
                  if not income_kw.empty else income)

    if income_all.empty:
        ins("blue", "ℹ️", "אין הכנסות מתועדות",
            "הכנסות מזוהות לפי חשבונות {927, 951, 7367} או מילות מפתח כמו "
            "'הכנסות', 'חיוב ספק'. ודא שהמאזן/כרטיס ההנהלה כולל אותם.")
        return

    total = float(income_all.loc[income_all["amount"] < 0, "amount"].sum() * -1
                  + income_all.loc[income_all["amount"] > 0, "amount"].sum())
    num_inv = int(len(income_all))
    c1, c2, c3 = st.columns(3)
    c1.metric("סה\"כ הכנסות", _fmt_money(total))
    c2.metric("מספר חשבוניות", str(num_inv))
    if "month" in income_all.columns and not income_all.empty:
        n_months = income_all["month"].nunique()
        c3.metric("ממוצע חודשי", _fmt_money(total / n_months) if n_months else "—")

    # ── חשבוניות לפי חודש ──
    sec("הכנסות לפי חודש")
    if "month" in income_all.columns:
        monthly = income_all.groupby("month")["amount"].sum().abs().reset_index()
        monthly.columns = ["חודש", "סכום"]
        monthly["סכום"] = monthly["סכום"].round(0)
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    # ── טבלת חשבוניות עם date/customer/invoice#/amount/status ──
    sec("פירוט חשבוניות מכירה")
    invoice_df = income_all.copy()
    invoice_df["amount_abs"] = invoice_df["amount"].abs()
    if "description" in invoice_df.columns:
        invoice_df["invoice_num"] = invoice_df["description"].apply(_extract_invoice_num)
    else:
        invoice_df["invoice_num"] = ""
    invoice_df["status"] = "—"  # placeholder - דורש מעקב גבייה חיצוני

    show_cols = []
    rename_map = {}
    for src, heb in [
        ("date", "תאריך"),
        ("supplier", "לקוח"),
        ("invoice_num", "מס' חשבונית"),
        ("amount_abs", "סכום (₪)"),
        ("month", "חודש"),
        ("status", "סטטוס גבייה"),
        ("description", "פרטים"),
    ]:
        if src in invoice_df.columns:
            show_cols.append(src)
            rename_map[src] = heb

    disp = invoice_df[show_cols].copy()
    if "amount_abs" in disp.columns:
        disp["amount_abs"] = disp["amount_abs"].round(0)
    disp = disp.sort_values("date" if "date" in show_cols else show_cols[0])
    disp.columns = [rename_map[c] for c in show_cols]
    st.dataframe(disp, use_container_width=True, hide_index=True)

    ins("blue", "ℹ️", "סטטוס גבייה",
        "סטטוס שולם/פתוח לא מנוטר אוטומטית מחשבשבת. לתצוגה מלאה - "
        "חבר קובץ <code>collections.xlsx</code> או מערכת CRM.")


# ─── Tab 3: הוצאות (עם drill-down) ──────────────────────────
def _tab_expenses(df: pd.DataFrame) -> None:
    sec("הוצאות לפי קטגוריה")
    # רק חשבשבת ורק חיובי (הוצאות בפועל)
    exp_df = df[(df["source"] == "chashbashevet")] if "source" in df.columns else df.iloc[0:0]
    exp_df = exp_df[exp_df["amount"] > 0] if "amount" in exp_df.columns else exp_df

    if exp_df.empty:
        ins("blue", "ℹ️", "אין הוצאות מתועדות", "טען קובץ chashbashevet.xlsx לחודש.")
        return

    # ── סיכום עליון ──
    total_exp = float(exp_df["amount"].sum())
    st.metric("סה\"כ הוצאות בפרויקט", _fmt_money(total_exp))

    # ── חלוקה לקטגוריות לפי מילות מפתח + "אחר" לכל מה שלא נופל ──
    buckets: dict[str, pd.DataFrame] = {}
    matched_indices: set = set()
    for label, keywords in KEYWORD_CATEGORIES.items():
        if label == "income":
            continue
        sub = _filter_by_keywords(exp_df, keywords)
        if not sub.empty:
            buckets[label] = sub
            matched_indices.update(sub.index.tolist())

    # שורות שלא תפסו אף קטגוריה
    other = exp_df[~exp_df.index.isin(matched_indices)]
    if not other.empty:
        buckets["other"] = other

    # ── טבלת סיכום ──
    summary_rows = []
    for label, sub in buckets.items():
        s = float(sub["amount"].sum())
        summary_rows.append({
            "קטגוריה": _label_he(label),
            "סכום (₪)": round(s, 0),
            "תנועות": int(len(sub)),
            "% מסך": round(s / total_exp * 100, 1) if total_exp else 0,
            "_key": label,
        })
    summary_rows.sort(key=lambda r: -r["סכום (₪)"])
    summary_df = pd.DataFrame(summary_rows).drop(columns=["_key"])
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    # ── Drill-down: expander לכל קטגוריה ──
    sec("פירוט תנועות לכל קטגוריה", meta="לחץ על קטגוריה לפתיחה")
    for row in summary_rows:
        label_he = row["קטגוריה"]
        key = row["_key"]
        sub = buckets[key]
        with st.expander(
            f"{label_he} — {_fmt_money(row['סכום (₪)'])} · {row['תנועות']} תנועות",
            expanded=False,
        ):
            cols = [c for c in ["date", "account_num", "account_name", "supplier",
                                "description", "debit", "credit", "amount", "month"]
                    if c in sub.columns]
            disp = sub[cols].copy().sort_values("date" if "date" in cols else cols[0])
            heb_names = {
                "date": "תאריך", "account_num": "חשבון", "account_name": "שם חשבון",
                "supplier": "ספק", "description": "פרטים",
                "debit": "חובה", "credit": "זכות", "amount": "סכום", "month": "חודש",
            }
            disp.columns = [heb_names.get(c, c) for c in disp.columns]
            st.dataframe(disp, use_container_width=True, hide_index=True)


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


# ─── Tab 6: סולר ואחזקה (מודול מלא) ─────────────────────────
def _tab_fuel_maintenance(df: pd.DataFrame) -> None:
    solar = df[df["source"] == "solar"] if "source" in df.columns else df.iloc[0:0]
    hours = df[df["source"] == "hours"] if "source" in df.columns else df.iloc[0:0]
    # קניות סולר מחשבשבת (מילות מפתח: סולר/דלק)
    fuel_purchases = _filter_by_keywords(df, KEYWORD_CATEGORIES["fuel"])
    if "source" in fuel_purchases.columns:
        fuel_purchases = fuel_purchases[fuel_purchases["source"] == "chashbashevet"]
    if "amount" in fuel_purchases.columns:
        fuel_purchases = fuel_purchases[fuel_purchases["amount"] > 0]

    # ── KPIs עליונים ──
    total_liters = float(solar["liters"].sum()) if "liters" in solar.columns and not solar.empty else 0.0
    total_cost = float(fuel_purchases["amount"].sum()) if not fuel_purchases.empty else 0.0
    num_fuelings = int(len(solar))
    avg_price = total_cost / total_liters if total_liters > 0 else 0.0
    total_work_h = float(hours["work_hours"].sum()) if "work_hours" in hours.columns and not hours.empty else 0.0
    cost_per_hour = total_cost / total_work_h if total_work_h > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה\"כ ליטרים", f"{total_liters:,.0f}")
    c2.metric("סה\"כ עלות", _fmt_money(total_cost))
    c3.metric("₪ / ליטר", f"{avg_price:.2f}" if avg_price else "—")
    c4.metric("₪ / שעת עבודה", f"{cost_per_hour:,.0f}" if cost_per_hour else "—")
    st.caption(f"{num_fuelings} תדלוקים · {int(total_work_h):,} שעות עבודה")

    # ── מאזן מלאי (placeholder) ──
    sec("מאזן מלאי סולר", meta="מצריך קלט ידני של פתיחה/סגירה")
    st.markdown(
        f"""<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
        padding:14px 18px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
          <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
            letter-spacing:.8px;font-weight:700">מלאי פתיחה</div>
            <div style="font-size:18px;font-weight:800;color:#94A3B8">— ל'</div></div>
          <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
            letter-spacing:.8px;font-weight:700">+ קניות</div>
            <div style="font-size:18px;font-weight:800;color:var(--status-good)">
              {total_liters:,.0f} ל'</div></div>
          <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
            letter-spacing:.8px;font-weight:700">− שימושים</div>
            <div style="font-size:18px;font-weight:800;color:var(--status-bad)">
              {total_liters:,.0f} ל'</div></div>
          <div><div style="font-size:10px;color:#64748B;text-transform:uppercase;
            letter-spacing:.8px;font-weight:700">= מלאי סגירה</div>
            <div style="font-size:18px;font-weight:800;color:#94A3B8">— ל'</div></div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.caption("מלאי פתיחה/סגירה לא מנוטרים אוטומטית. לתצוגה מלאה - הוסף קובץ "
               "<code>fuel_inventory.xlsx</code> עם עמודות month/opening_l/closing_l.")

    # ── קניות סולר לפי ספק ──
    sec("קניות סולר לפי ספק")
    if fuel_purchases.empty:
        st.caption("לא זוהו רכישות סולר ב-chashbashevet (חשבונות עם 'סולר'/'דלק').")
    else:
        by_sup = fuel_purchases.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_sup.columns = ["ספק", "סה\"כ (₪)", "חשבוניות"]
        by_sup["סה\"כ (₪)"] = by_sup["סה\"כ (₪)"].round(0)
        st.dataframe(by_sup.sort_values("סה\"כ (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט חשבוניות סולר"):
            cols = [c for c in ["date", "supplier", "description", "amount", "month"]
                    if c in fuel_purchases.columns]
            st.dataframe(fuel_purchases[cols].sort_values("date" if "date" in cols else cols[0]),
                         use_container_width=True, hide_index=True)

    # ── צריכה לפי רכב/כלי ──
    sec("צריכה לפי כלי", meta="מתוך solar.xlsx")
    if solar.empty:
        ins("blue", "ℹ️", "אין נתוני תדלוק", "טען <code>solar.xlsx</code> לחודש.")
    else:
        by_tool = solar.groupby(["license_num", "tool_name"])["liters"].agg(
            ["sum", "count"]
        ).reset_index()
        by_tool.columns = ["מס' רישוי", "שם כלי", "סה\"כ ליטרים", "תדלוקים"]
        by_tool["סה\"כ ליטרים"] = by_tool["סה\"כ ליטרים"].round(0)

        # הוסף עלות משוערת (משערך לפי avg_price)
        if avg_price > 0:
            by_tool["עלות משוערת (₪)"] = (by_tool["סה\"כ ליטרים"] * avg_price).round(0)
        st.dataframe(by_tool.sort_values("סה\"כ ליטרים", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט תדלוקים"):
            cols = [c for c in ["date", "tool_name", "license_num", "liters",
                                "engine_hours", "lph_calculated"]
                    if c in solar.columns]
            st.dataframe(solar[cols].sort_values("date"),
                         use_container_width=True, hide_index=True)

    # ── תדלוקים ללא שעות עבודה (חשד) ──
    sec("תדלוקים ללא שעות עבודה (חשד לבזבוז)")
    from core import solar_loader, hours_loader
    from pipeline import _load_tools_registry
    if not solar.empty:
        sm = solar_loader.aggregate_by_tool_month(solar)
        hm = hours_loader.aggregate_by_tool_month(hours) if not hours.empty else pd.DataFrame(
            columns=["license_num", "month", "total_work_hours"]
        )
        no_hrs = anomaly_detector.detect_solar_without_hours(sm, hm, _load_tools_registry())
        if no_hrs.empty:
            ins("green", "✓", "כל הכלים שתודלקו אכן עבדו", "אין תדלוקים יתומים.")
        else:
            disp = no_hrs.copy()
            disp["estimated_waste_nis"] = disp["estimated_waste_nis"].round(0)
            disp.columns = ["מס' רישוי", "שם כלי", "סוג כלי", "חודש",
                            "סה\"כ ליטרים", "בזבוז משוער (₪)"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── אחזקות ──
    sec("אחזקות - מוסך, תיקונים, חלפים")
    maint = _filter_by_keywords(df, KEYWORD_CATEGORIES["maintenance"])
    if "source" in maint.columns:
        maint = maint[maint["source"] == "chashbashevet"]
    if "amount" in maint.columns:
        maint = maint[maint["amount"] > 0]
    if maint.empty:
        st.caption("אין תנועות תחת מילות מפתח 'אחזקת', 'מוסך', 'תיקונים'.")
    else:
        total_m = float(maint["amount"].sum())
        st.metric("סה\"כ אחזקה", _fmt_money(total_m))
        by_supm = maint.groupby("supplier")["amount"].agg(["sum", "count"]).reset_index()
        by_supm.columns = ["ספק / מוסך", "סה\"כ (₪)", "תנועות"]
        by_supm["סה\"כ (₪)"] = by_supm["סה\"כ (₪)"].round(0)
        st.dataframe(by_supm.sort_values("סה\"כ (₪)", ascending=False),
                     use_container_width=True, hide_index=True)

        with st.expander("פירוט תנועות אחזקה"):
            cols = [c for c in ["date", "month", "account_name", "supplier",
                                "description", "amount"] if c in maint.columns]
            st.dataframe(maint[cols].sort_values("date" if "date" in cols else cols[0]),
                         use_container_width=True, hide_index=True)


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
