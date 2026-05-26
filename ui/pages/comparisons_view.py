"""מסך השוואות — בין חודשים ובין פרויקטים.

נגיש מהמסך הראשי דרך כפתור "📊 השוואות" (לפני בחירת פרויקט).

שני מצבים:
    1. בין חודשים — בוחרים פרויקט ושני חודשים+ → KPIs מקבילים
    2. בין פרויקטים — מציג טבלה של כל הפרויקטים עם KPIs + ranking
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.components import breadcrumb, empty_state, ins, sec
from ui.formatters import (
    display_dataframe, format_currency, format_number, format_percent,
)


def render_comparisons_page(df_master: pd.DataFrame,
                              projects: list[dict]) -> None:
    """דף השוואות עם 2 טאבים: בין חודשים ובין פרויקטים."""
    # ── כפתור חזרה ──
    back_col, _ = st.columns([1, 5])
    with back_col:
        if st.button("← חזרה למסך הראשי", key="comparisons_back",
                       use_container_width=True):
            st.session_state.pop("view", None)
            st.rerun()

    breadcrumb("ניווט ראשי", "השוואות")
    sec("📊 השוואות")

    tabs = st.tabs(["📅 בין חודשים (בתוך פרויקט)", "🏗 בין פרויקטים"])

    with tabs[0]:
        _render_month_comparison(df_master, projects)
    with tabs[1]:
        _render_project_comparison(df_master, projects)


# ── 1. השוואה בין חודשים ──────────────────────────────────

def _render_month_comparison(df_master: pd.DataFrame,
                                projects: list[dict]) -> None:
    from core.comparisons import compare_months
    from core.project_store import validate_project_status

    if not projects:
        empty_state(icon="ti-buildings-off", title="אין פרויקטים",
                      body_html="צריך לפחות פרויקט אחד כדי להשוות חודשים.")
        return

    breadcrumb("השוואות", "בין חודשים")

    # בחירת פרויקט
    active = [p for p in projects
              if validate_project_status(p.get("status")) != "archived"]
    project_names = [p["project_name"] for p in active]
    if not project_names:
        st.caption("אין פרויקטים פעילים להשוואה.")
        return

    pick_name = st.selectbox("בחר פרויקט", project_names,
                                 key="comp_month_pick_project")
    project = next(p for p in active if p["project_name"] == pick_name)
    pid = project["project_id"]

    # רשימת חודשים זמינים
    project_df = df_master[df_master["project_id"] == pid] \
        if not df_master.empty and "project_id" in df_master.columns \
        else pd.DataFrame()
    months_avail = sorted(project_df["month"].dropna().unique()) \
        if "month" in project_df.columns else []
    if len(months_avail) < 2:
        ins("blue", "ℹ️", "צריך לפחות 2 חודשים להשוואה",
            f"בפרויקט '{pick_name}' יש {len(months_avail)} חודש בלבד.")
        return

    # בחירת חודשים — multiselect
    chosen = st.multiselect(
        "בחר חודשים להשוואה (לפחות 2)",
        months_avail,
        default=months_avail[-3:] if len(months_avail) >= 3 else months_avail,
        key="comp_month_pick_months",
    )
    if len(chosen) < 2:
        st.caption("בחר לפחות 2 חודשים.")
        return

    # סדר כרונולוגי
    chosen = sorted(chosen, key=lambda m: pd.to_datetime(m, format="%m-%Y",
                                                             errors="coerce"))

    # חישוב
    df_cmp = compare_months(df_master, pid, chosen)
    if df_cmp.empty:
        st.caption("אין נתונים להשוואה.")
        return

    # תצוגה — שלוש שורות עיקריות + טבלה
    sec("KPIs מקבילים")
    cols = st.columns(len(chosen))
    for i, (col, m) in enumerate(zip(cols, chosen)):
        row = df_cmp.iloc[i]
        with col:
            st.markdown(f"### 📅 {m}")
            st.metric("הכנסות", format_currency(row["revenue"]))
            st.metric("הוצאות", format_currency(row["expenses"]))
            st.metric("רווח", format_currency(row["profit"]))
            st.metric("דלק", format_currency(row["fuel_cost"]))
            if pd.notna(row.get("change_revenue_pct")):
                st.caption(f"שינוי הכנסות מהחודש הקודם: "
                            f"{format_percent(row['change_revenue_pct'], already_pct=True)}")

    # ── טבלה מלאה ──
    sec("השוואה מלאה")
    disp = df_cmp.copy()
    rename = {
        "month":                "חודש",
        "revenue":              "הכנסות",
        "change_revenue_pct":   "Δ הכנסות (%)",
        "expenses":             "הוצאות",
        "change_expenses_pct":  "Δ הוצאות (%)",
        "profit":               "רווח / הפסד",
        "change_profit_pct":    "Δ רווח (%)",
        "fuel_cost":            "דלק",
        "change_fuel_pct":      "Δ דלק (%)",
        "fuel_liters":          "ליטרים",
        "work_hours":           "שעות עבודה",
        "num_tx":               "תנועות",
        "num_suppliers":        "ספקים",
    }
    disp = disp.rename(columns=rename)
    display_dataframe(disp)

    # ── מסקנה ──
    if len(chosen) >= 2:
        first_row = df_cmp.iloc[0]
        last_row = df_cmp.iloc[-1]
        rev_change = ((last_row["revenue"] - first_row["revenue"])
                      / first_row["revenue"] * 100) if first_row["revenue"] else 0
        exp_change = ((last_row["expenses"] - first_row["expenses"])
                      / first_row["expenses"] * 100) if first_row["expenses"] else 0
        if rev_change > 0 and exp_change < rev_change:
            ins("green", "✓", f"מגמה חיובית: הכנסות עלו {rev_change:.0f}%",
                f"הוצאות עלו {exp_change:.0f}% — קצב הצמיחה מהיר יותר.")
        elif exp_change > rev_change + 20:
            ins("red", "🚨", f"הוצאות גדלות מהר מההכנסות",
                f"הוצאות: +{exp_change:.0f}% | הכנסות: +{rev_change:.0f}%")
        else:
            ins("blue", "ℹ️", "השוואה הוצגה",
                f"הכנסות: {rev_change:+.0f}% | הוצאות: {exp_change:+.0f}%")


# ── 2. השוואה בין פרויקטים ────────────────────────────────

def _render_project_comparison(df_master: pd.DataFrame,
                                  projects: list[dict]) -> None:
    from core.comparisons import compare_projects
    from core.project_store import validate_project_status, STATUS_HE

    breadcrumb("השוואות", "בין פרויקטים")

    if not projects:
        empty_state(icon="ti-buildings-off", title="אין פרויקטים",
                      body_html="צריך פרויקטים כדי להשוות.")
        return

    # פילטר סטטוס
    fcol1, _ = st.columns([2, 4])
    with fcol1:
        scope = st.selectbox(
            "כולל סטטוס",
            ["פעילים בלבד", "כל הפרויקטים", "כולל ארכיון"],
            index=0,
        )

    if scope == "פעילים בלבד":
        relevant = [p for p in projects
                    if validate_project_status(p.get("status"))
                       in ("active", "future")]
    elif scope == "כולל ארכיון":
        relevant = projects
    else:
        relevant = [p for p in projects
                    if validate_project_status(p.get("status")) != "archived"]

    if not relevant:
        st.caption("אין פרויקטים מתאימים לסינון.")
        return

    pids = [p["project_id"] for p in relevant]
    df_cmp = compare_projects(df_master, pids)
    if df_cmp.empty:
        st.caption("אין נתונים להשוואה.")
        return

    # ── KPIs אגרגטיביים ──
    sec("סיכום כולל")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה\"כ פרויקטים", format_number(len(df_cmp)))
    c2.metric("הכנסות מצרפיות", format_currency(df_cmp["revenue"].sum()))
    c3.metric("הוצאות מצרפיות", format_currency(df_cmp["expenses"].sum()))
    c4.metric("רווח כולל", format_currency(df_cmp["profit"].sum()))

    # ── טבלה מסודרת ──
    sec("טבלת השוואה")
    disp = df_cmp.copy()
    disp["profit_pct"] = disp["profit_pct"].round(1)
    rename = {
        "project_id":      "מזהה",
        "project_name":    "שם פרויקט",
        "status":          "סטטוס",
        "revenue":         "הכנסות",
        "expenses":        "הוצאות",
        "profit":          "רווח / הפסד",
        "profit_pct":      "% רווחיות",
        "fuel_cost":       "עלות דלק",
        "fuel_liters":     "ליטרים",
        "work_hours":      "שעות עבודה",
        "num_tx":          "תנועות",
        "num_suppliers":   "ספקים",
    }
    disp = disp.rename(columns=rename)
    display_dataframe(disp)

    # ── Top performers ──
    sec("מובילים בכל קטגוריה")
    if not df_cmp.empty:
        cards = st.columns(4)
        with cards[0]:
            best = df_cmp.nlargest(1, "profit").iloc[0]
            st.markdown(f"**🏆 הכי רווחי**")
            st.markdown(f"{best['project_name']}")
            st.caption(format_currency(best["profit"]))
        with cards[1]:
            worst = df_cmp.nsmallest(1, "profit").iloc[0]
            st.markdown(f"**🚨 הכי בהפסד**")
            st.markdown(f"{worst['project_name']}")
            st.caption(format_currency(worst["profit"]))
        with cards[2]:
            top_exp = df_cmp.nlargest(1, "expenses").iloc[0]
            st.markdown(f"**💰 הכי יקר**")
            st.markdown(f"{top_exp['project_name']}")
            st.caption(format_currency(top_exp["expenses"]))
        with cards[3]:
            if df_cmp["fuel_cost"].sum() > 0:
                top_fuel = df_cmp.nlargest(1, "fuel_cost").iloc[0]
                st.markdown(f"**⛽ הכי הרבה דלק**")
                st.markdown(f"{top_fuel['project_name']}")
                st.caption(format_currency(top_fuel["fuel_cost"]))
            else:
                st.markdown(f"**⛽ דלק**")
                st.caption("אין נתוני דלק")
