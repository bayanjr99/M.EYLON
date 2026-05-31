"""מסך הזנת נתונים ידנית בסגנון אקסל — סולר ושעות עבודה.

המשתמש מדביק נתונים ישירות מאקסל לטבלה (st.data_editor), עורך/מוסיף/מוחק
שורות, בודק (analyze) ושומר (apply_import). הנתונים נכנסים ל-manual_store
ומשם זורמים ל-master.parquet (pipeline.aggregate_manual_*) — כך הם משפיעים
על כל הטאבים, ה-KPIs והגרפים בדף הפרויקט, ממוינים לחודש לפי תאריך השורה.

זרימה:
    1. בחירת סוג דוח (תת-טאב: סולר / שעות עבודה)
    2. בחירת פרויקט + חודש יעד
    3. הדבקה / עריכה בטבלה (כולל הדבקה מרובת-שורות מאקסל)
    4. "בדוק נתונים" — סיכום תקין/שגוי/כפילויות/סכומים
    5. "שמור" — שמירה + build_master + רענון הדשבורד
"""
from __future__ import annotations

import io
import logging
from datetime import date as _date

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

from core import manual_store
from pipeline import build_master
from ui.components import empty_state, ins, sec
from ui.formatters import format_currency, format_number


_MODE_LABELS = {
    "add_new": "הוסף רק שורות חדשות (מומלץ)",
    "update_existing": "עדכן שורות קיימות + הוסף חדשות",
    "replace_month": "החלף את כל הנתונים בחודש היעד",
    "check_only": "בדיקה בלבד — ללא שמירה",
}

# מספר שורות ריקות בטבלה בעת איפוס
_BLANK_ROWS = 10


# ── עזרי טבלה ─────────────────────────────────────────────────
def _column_config(kind: str) -> dict:
    """בונה column_config ל-st.data_editor לפי הגדרת העמודות ב-manual_store."""
    labels = manual_store.column_labels(kind)
    select_opts = manual_store.KINDS[kind].get("select_options", {})
    cfg: dict = {}
    for key in manual_store.column_keys(kind):
        ck = manual_store.column_kind(kind, key)
        label = labels[key]
        if ck == "date":
            cfg[key] = st.column_config.DateColumn(label, format="DD/MM/YYYY")
        elif ck == "int":
            cfg[key] = st.column_config.NumberColumn(label, step=1, format="%d")
        elif ck == "float":
            cfg[key] = st.column_config.NumberColumn(label, format="%.2f")
        elif ck == "select":
            cfg[key] = st.column_config.SelectboxColumn(
                label, options=select_opts.get(key, []))
        else:
            cfg[key] = st.column_config.TextColumn(label)
    return cfg


def _blank_frame(kind: str, n: int = _BLANK_ROWS) -> pd.DataFrame:
    """DataFrame עם n שורות ריקות בטיפוסים הנכונים (לזריעת ה-editor)."""
    base = manual_store.empty_frame(kind)
    return base.reindex(range(n)).reset_index(drop=True)


def _parse_tsv(kind: str, text: str) -> pd.DataFrame | None:
    """ממיר טקסט מודבק מאקסל (TSV) ל-DataFrame לפי סדר העמודות של ה-kind.

    מתעלם משורת כותרת אם זוהתה (כשהתא הראשון אינו תאריך/מספר).
    """
    if not text or not text.strip():
        return None
    try:
        raw = pd.read_csv(io.StringIO(text.strip("\n")), sep="\t",
                          header=None, dtype=str)
    except Exception as e:
        logger.warning("TSV paste parse failed: %s", e)
        return None
    if raw.empty:
        return None
    keys = manual_store.column_keys(kind)
    raw = raw.iloc[:, : len(keys)]
    raw.columns = keys[: raw.shape[1]]
    for k in keys:
        if k not in raw.columns:
            raw[k] = None
    raw = raw[keys]
    # זיהוי שורת כותרת: אם התא הראשון אינו תאריך תקין וגם תואם לאחת התוויות
    first = str(raw.iloc[0, 0] or "").strip()
    if first and pd.isna(pd.to_datetime(first, errors="coerce", dayfirst=True)):
        labels = set(manual_store.column_labels(kind).values())
        if first in labels or first in {"תאריך", "date"}:
            raw = raw.iloc[1:].reset_index(drop=True)
    if raw.empty:
        return None
    return manual_store._coerce_types(kind, raw)


def _to_excel_bytes(kind: str, df: pd.DataFrame) -> bytes:
    """ממיר את הטבלה לקובץ אקסל (כותרות עברית) להורדה."""
    out = io.BytesIO()
    labels = manual_store.column_labels(kind)
    keys = [k for k in manual_store.column_keys(kind) if k in df.columns]
    disp = df[keys].rename(columns=labels)
    try:
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            disp.to_excel(writer, index=False, sheet_name="נתונים")
    except Exception as e:
        logger.warning("excel export failed: %s", e)
        return b""
    return out.getvalue()


# ── סיכום בדיקה ────────────────────────────────────────────────
def _render_summary(kind: str, summary: dict, mode_key: str) -> None:
    """מציג את סיכום ה-analyze: תקין/שגוי/כפילויות/חדשות + סכומים."""
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("שורות בטבלה", f"{summary['rows_in_file']:,}")
    m2.metric("שורות תקינות", f"{summary['valid_count']:,}")
    m3.metric("שורות עם שגיאה", f"{summary['error_count']:,}")
    m4.metric("כפילויות (קיימות)", f"{summary['duplicate_count']:,}")

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("שורות חדשות", f"{summary['new_count']:,}")
    n2.metric("שורות שהשתנו", f"{summary['updated_count']:,}")
    if kind == "solar":
        n3.metric('סה"כ ליטרים', format_number(summary.get("liters_sum", 0)))
        n4.metric('סה"כ סכום', format_currency(summary.get("amount_sum", 0)))
    else:
        n3.metric('סה"כ שעות', format_number(summary.get("hours_sum", 0)))
        n4.metric('סה"כ עלות', format_currency(summary.get("amount_sum", 0)))

    if summary["months"]:
        st.caption("חודשים מושפעים: " + ", ".join(summary["months"]))
    st.caption(f"מאגר לפני: {summary['store_before']:,} → אחרי: "
               f"{summary['store_after']:,} שורות")

    if summary["error_count"]:
        ins("amber", "⚠️", "שורות לא תקינות",
            f"{summary['error_count']} שורות חסרות תאריך או שדה חובה — "
            "הן לא יישמרו. תקן אותן בטבלה ובדוק שוב.")
    if summary["duplicate_count"]:
        ins("blue", "🔁", "נמצאו שורות שכבר קיימות במערכת",
            f"{summary['duplicate_count']} שורות זהות כבר במאגר — יידולגו "
            "במצב 'הוסף רק חדשות'.")
    if summary["updated_count"] and mode_key == "add_new":
        ins("amber", "✏️", "שורות עם ערכים שהשתנו",
            f"{summary['updated_count']} שורות עם אותו מפתח אך ערכים שונים. "
            "במצב 'הוסף רק חדשות' הן ייכנסו כשורה נוספת — לעדכון בחר "
            "'עדכן שורות קיימות'.")


# ── תת-טאב לכל סוג דוח ─────────────────────────────────────────
def _render_kind(kind: str, projects: list[dict]) -> None:
    """מצייר את מסך ההזנה לסוג דוח בודד (solar / hours)."""
    from core import db

    # ── 1. פרויקט + חודש יעד ──
    sec("1. פרויקט וחודש")
    c1, c2 = st.columns([2, 1])
    with c1:
        names = [p["project_name"] for p in projects]
        pick = st.selectbox("פרויקט", names, key=f"man_proj_{kind}")
        project = next(p for p in projects if p["project_name"] == pick)
        project_id = project["project_id"]
        project_name = project["project_name"]
    with c2:
        month_date = st.date_input(
            "חודש יעד (להחלפת חודש)", value=_date.today(),
            key=f"man_month_{kind}", format="DD/MM/YYYY")
        target_month = month_date.strftime("%m-%Y")
    st.caption("כל שורה משויכת לחודש לפי *התאריך שבה* — חודש היעד משמש רק "
               "במצב 'החלף את כל הנתונים בחודש'.")

    # ── 2. הדבקה מאקסל (אופציונלי) ──
    rev_key = f"man_rev_{kind}_{project_id}"
    seed_key = f"man_seed_{kind}_{project_id}"
    rev = st.session_state.get(rev_key, 0)

    with st.expander("📋 הדבקת נתונים מאקסל (מרובה שורות)", expanded=False):
        st.caption("העתק את התאים מאקסל (כולל/ללא כותרת) והדבק כאן. "
                   "סדר העמודות צריך להתאים לטבלה למטה.")
        tsv = st.text_area("הדבק כאן", height=120, key=f"man_tsv_{kind}_{rev}",
                           label_visibility="collapsed")
        if st.button("⬇️ הדבק לטבלה", key=f"man_paste_{kind}",
                     use_container_width=True):
            parsed = _parse_tsv(kind, tsv)
            if parsed is None or parsed.empty:
                st.warning("לא זוהו שורות בטקסט שהודבק.")
            else:
                st.session_state[seed_key] = parsed
                st.session_state[rev_key] = rev + 1
                st.rerun()

    # ── 3. הטבלה ──
    sec("2. טבלת נתונים")
    seed = st.session_state.get(seed_key)
    if seed is None or not isinstance(seed, pd.DataFrame) or seed.empty:
        seed = _blank_frame(kind)

    edited = st.data_editor(
        seed,
        key=f"man_editor_{kind}_{project_id}_{rev}",
        num_rows="dynamic",
        use_container_width=True,
        column_config=_column_config(kind),
        hide_index=True,
    )

    # ── 4. כפתורי פעולה ──
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("🧹 נקה טבלה", key=f"man_clear_{kind}",
                     use_container_width=True):
            st.session_state[seed_key] = _blank_frame(kind)
            st.session_state[rev_key] = rev + 1
            st.rerun()
    with b2:
        xls = _to_excel_bytes(kind, edited)
        st.download_button(
            "📤 ייצא לאקסל", data=xls,
            file_name=f"{kind}_{project_id}_{target_month}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"man_export_{kind}", use_container_width=True,
            disabled=not xls)
    with b3:
        existing = manual_store.load_store(project_id, kind)
        st.metric("שורות במאגר", f"{len(existing):,}")

    # ── 5. מצב שמירה + בדיקה ──
    sec("3. בדיקה ושמירה")
    mode_key = st.radio(
        "אופן השמירה",
        list(_MODE_LABELS.keys()),
        format_func=lambda k: _MODE_LABELS[k],
        key=f"man_mode_{kind}", horizontal=False)

    ccheck, csave = st.columns(2)
    with ccheck:
        do_check = st.button("🔎 בדוק נתונים", use_container_width=True,
                             key=f"man_check_{kind}")
    with csave:
        do_save = st.button("✅ שמור", type="primary", use_container_width=True,
                            key=f"man_save_{kind}",
                            disabled=mode_key == "check_only")

    if do_check or do_save:
        summary = manual_store.analyze(project_id, kind, edited, mode_key,
                                       target_month)
        if summary["rows_in_file"] == 0:
            st.info("הטבלה ריקה — אין מה לבדוק או לשמור.")
            return
        _render_summary(kind, summary, mode_key)

        if do_save and mode_key != "check_only":
            if summary["valid_count"] == 0:
                st.error("אין שורות תקינות לשמירה. תקן את השגיאות ונסה שוב.")
                return
            with st.spinner("שומר נתונים ובונה מאסטר מחדש..."):
                applied = manual_store.apply_import(
                    project_id, kind, edited, mode_key,
                    source_file="הזנה ידנית", target_month=target_month)
                try:
                    db.log_import(project_id, project_name,
                                  f"manual_{kind}", "הזנה ידנית",
                                  target_month, "ידני", mode_key,
                                  applied, "approved")
                except Exception as e:
                    logger.warning("log_import failed (non-fatal): %s", e)
                build_master()
                st.cache_data.clear()
            st.success(f"נשמרו {applied['valid_count']:,} שורות תקינות — "
                       "הדשבורד עודכן.")
            # אפס את הטבלה אחרי שמירה מוצלחת
            st.session_state[seed_key] = _blank_frame(kind)
            st.session_state[rev_key] = rev + 1


# ── מסך ראשי ──────────────────────────────────────────────────
def render_manual_entry_page(projects: list[dict]) -> None:
    """המסך הראשי להזנת נתונים ידנית (סולר / שעות עבודה)."""
    back_col, title_col = st.columns([1, 6])
    with back_col:
        if st.button("← חזרה לרשימה", key="manual_back",
                     use_container_width=True):
            st.session_state.pop("view", None)
            st.rerun()
    with title_col:
        st.markdown(
            """<div style="display:flex;align-items:center;gap:12px;
            padding:8px 16px;background:linear-gradient(135deg,#F0FDF4,#FFFFFF);
            border-radius:10px;border:1px solid var(--brand-primary-mid)">
              <i class="ti ti-table-plus" style="font-size:22px;color:var(--brand-primary)"></i>
              <div><div style="font-size:15px;font-weight:800;color:var(--ink-strong)">
                הזנת נתונים ידנית</div>
                <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">
                  הדבק נתוני סולר/שעות ישירות מאקסל — המערכת תזהה כפילויות,
                  תחשב סכומים ותעדכן את כל הטאבים לפי תאריך השורה
                </div></div></div>""",
            unsafe_allow_html=True,
        )

    if not projects:
        empty_state(
            icon="ti-buildings-off",
            title="אין פרויקטים ברשימת הפרויקטים",
            body_html="צריך לרשום פרויקט ברשימת הפרויקטים לפני הזנת נתונים.",
        )
        return

    tab_solar, tab_hours, tab_tools = st.tabs([
        "⛽ סולר", "⏱️ שעות עבודה", "🔧 כלים / ציוד",
    ])
    with tab_solar:
        _render_kind("solar", projects)
    with tab_hours:
        _render_kind("hours", projects)
    with tab_tools:
        empty_state(
            icon="ti-tools",
            title="כלים / ציוד — בקרוב",
            body_html="הזנת כלים וציוד תתווסף בשלב הבא. כרגע ניתן להזין "
                      "סולר ושעות עבודה.",
        )
