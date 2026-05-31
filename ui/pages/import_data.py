"""מסך ייבוא נתונים: העלאת קבצי חודש לפרויקט.

זרימה:
    1. בחירת פרויקט + חודש (MM-YYYY)
    2. הצגת קבצים קיימים (עם אפשרות מחיקה)
    3. העלאת קבצים חדשים (כרטיס/מאזן/סולר/שעות)
    4. שמירה לתיקיית הפרויקט/חודש
    5. הפעלת build_master() אוטומטית כדי לרענן את המאסטר
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

import streamlit as st

logger = logging.getLogger(__name__)

from pipeline import PROJECTS_ROOT, build_master, list_available_months
from ui.components import empty_state, ins, sec
from ui.formatters import display_dataframe, format_currency, format_number


_MONTH_RE = re.compile(r"^\d{2}-\d{4}$")


# מיפוי slot → רשימת מילות מפתח לזיהוי כפילות וכינוי בעברית
SLOTS: dict[str, dict] = {
    "chashbashevet": {
        "label": "כרטיס הנהלה",
        "default_name": "chashbashevet.xlsx",
        "keywords": ["כרטיס", "chashbashevet"],
        "required": True,
    },
    "balance": {
        "label": "מאזן",
        "default_name": "balance.xlsx",
        "keywords": ["מאזן", "balance"],
        "required": False,
    },
    "solar": {
        "label": "דוח תדלוק (סולר)",
        "default_name": "solar.xlsx",
        "keywords": ["סולר", "solar", "תדלוק"],
        "required": False,
    },
    "hours": {
        "label": "דוח שעות כלים",
        "default_name": "hours.xlsx",
        "keywords": ["שעות", "hours"],
        "required": False,
    },
    "fuel_inventory": {
        "label": "מאזן מלאי סולר",
        "default_name": "fuel_inventory.xlsx",
        "keywords": ["fuel_inventory", "מלאי סולר", "מלאי"],
        "required": False,
    },
}


def _existing_file_for_slot(month_dir: Path, slot_keywords: list[str]) -> Path | None:
    """מוצא קובץ קיים בחודש שתואם לאחת ממילות המפתח של ה-slot."""
    if not month_dir.exists():
        return None
    for f in month_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
            continue
        if f.name.startswith("~$"):
            continue
        name_lower = f.name.lower()
        for kw in slot_keywords:
            if kw.lower() in name_lower:
                return f
    return None


def render_import_page(projects: list[dict]) -> None:
    """המסך הראשי לייבוא נתונים — מפצל בין יבוא מצטבר ליבוא קבצי-חודש."""
    # ── Back button + header ──
    back_col, title_col = st.columns([1, 6])
    with back_col:
        if st.button("← חזרה לרשימה", key="import_back", use_container_width=True):
            st.session_state.pop("view", None)
            st.rerun()
    with title_col:
        st.markdown(
            """<div style="display:flex;align-items:center;gap:12px;
            padding:8px 16px;background:linear-gradient(135deg,#F0FDF4,#FFFFFF);
            border-radius:10px;border:1px solid var(--brand-primary-mid)">
              <i class="ti ti-upload" style="font-size:22px;color:var(--brand-primary)"></i>
              <div><div style="font-size:15px;font-weight:800;color:var(--ink-strong)">
                יבוא דוחות</div>
                <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">
                  העלה דוח כרטסת/מאזן מצטבר (עד היום) — המערכת תזהה כפילויות
                  ותעדכן לבד את כל החודשים לפי תאריך התנועה
                </div></div></div>""",
            unsafe_allow_html=True,
        )

    if not projects:
        empty_state(
            icon="ti-buildings-off",
            title="אין פרויקטים ברשימת הפרויקטים",
            body_html="צריך לרשום פרויקט ברשימת הפרויקטים לפני ייבוא.",
        )
        return

    tab_cum, tab_month, tab_hist = st.tabs([
        "📥 דוחות מצטברים (כרטסת/מאזן)",
        "🗂️ קבצי חודש (סולר/שעות/מתקדם)",
        "🕓 היסטוריית יבוא",
    ])
    with tab_cum:
        _render_cumulative_import(projects)
    with tab_month:
        _render_monthly_import(projects)
    with tab_hist:
        _render_import_history(projects)


def _render_monthly_import(projects: list[dict]) -> None:
    """ייבוא קבצי חודש קלאסי (כרטיס/מאזן/סולר/שעות לפי תיקיית MM-YYYY)."""
    if not projects:
        empty_state(
            icon="ti-buildings-off",
            title="אין פרויקטים ברשימת הפרויקטים",
            body_html="צריך לרשום פרויקט ברשימת הפרויקטים לפני ייבוא.",
        )
        return

    # אזהרה אם רץ ב-Streamlit Cloud (FS לא קבוע)
    import os
    if os.environ.get("STREAMLIT_SHARING_MODE") or "/mount/src" in os.getcwd():
        ins("amber", "⚠️", "ענן: העלאות לא נשמרות לאורך זמן",
            "בענן מערכת הקבצים מאתחלת בכל פריסה. להעלאה קבועה - "
            "הרץ מקומית או דחוף ידנית את מאסטר הנתונים למאגר.")

    # ── 1. בחירת פרויקט וחודש ──
    sec("בחר פרויקט וחודש")
    col_p, col_m = st.columns([2, 1])
    with col_p:
        project_names = [p["project_name"] for p in projects]
        pick_name = st.selectbox("פרויקט", project_names, key="imp_project")
        project = next(p for p in projects if p["project_name"] == pick_name)
        project_id = project["project_id"]

    with col_m:
        month = st.text_input(
            "חודש (פורמט: MM-YYYY)", key="imp_month",
        ).strip()

    # ── אזהרת סטטוס: פרויקט שהסתיים ──
    from core.project_store import validate_project_status, STATUS_HE
    proj_status = validate_project_status(project.get("status"))
    if proj_status == "completed":
        confirm_key = f"imp_confirm_completed_{project_id}"
        if not st.session_state.get(confirm_key):
            st.warning(
                f"⚠️ הפרויקט **{pick_name}** מסומן כ-**{STATUS_HE['completed']}**. "
                "האם אתה בטוח שברצונך לייבא אליו נתונים?"
            )
            cc_yes, cc_no = st.columns([1, 4])
            with cc_yes:
                if st.button("✅ כן, המשך", key=f"yes_{project_id}",
                               type="primary", use_container_width=True):
                    st.session_state[confirm_key] = True
                    st.rerun()
            return
    elif proj_status == "future":
        st.info(
            f"📅 הפרויקט **{pick_name}** מסומן כ-**{STATUS_HE['future']}**. "
            "ההעלאה תיעשה ידנית רק לאחר בחירתך."
        )

    if not month:
        st.info("הזן חודש לפי הפורמט MM-YYYY כדי להמשיך.")
        return
    if not _MONTH_RE.match(month):
        st.error(f"פורמט חודש לא תקין: '{month}'. השתמש ב-MM-YYYY.")
        return

    month_dir = PROJECTS_ROOT / project_id / month
    month_dir.mkdir(parents=True, exist_ok=True)

    # ── אזהרת חודש סגור ──
    try:
        from core import month_locks
        if month_locks.is_locked(project_id, month):
            confirm_key = f"imp_locked_confirm_{project_id}_{month}"
            if not st.session_state.get(confirm_key):
                st.error(
                    f"🔒 חודש **{month}** סגור (נעול). ייבוא לחודש סגור עלול "
                    "לשנות דוחות שכבר הופקו. דורש אישור מפורש."
                )
                cc, _ = st.columns([1, 4])
                with cc:
                    if st.button("✅ אני מאשר ייבוא לחודש סגור",
                                   key=f"yes_locked_{project_id}_{month}",
                                   type="primary",
                                   use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()
                return
    except Exception:
        pass

    # ── 2. הצגת חודשים קיימים בפרויקט ──
    existing_months = list_available_months(project_id)
    if existing_months:
        st.caption(f"חודשים קיימים בפרויקט: {', '.join(existing_months)}")

    # ── 3. הצגת קבצים קיימים בחודש הנבחר + אפשרות מחיקה ──
    sec(f"קבצים קיימים ל-{project_id} / {month}")
    files_present = {}
    for slot_key, slot in SLOTS.items():
        existing = _existing_file_for_slot(month_dir, slot["keywords"])
        files_present[slot_key] = existing

    rows_html = []
    for slot_key, slot in SLOTS.items():
        ex = files_present[slot_key]
        if ex:
            size_kb = ex.stat().st_size // 1024
            status = f'<span style="color:var(--status-good);font-weight:700">✓ {ex.name}</span> ' \
                     f'<span style="color:var(--ink-faint)">({size_kb:,} KB)</span>'
        else:
            req = " (חובה)" if slot["required"] else ""
            status = f'<span style="color:var(--ink-faint)">— לא הועלה{req}</span>'
        rows_html.append(
            f'<tr><td style="padding:8px;font-weight:600">{slot["label"]}</td>'
            f'<td style="padding:8px">{status}</td></tr>'
        )
    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;background:#fff;'
        f'border:1px solid var(--line);border-radius:8px;overflow:hidden">'
        f'{"".join(rows_html)}</table>',
        unsafe_allow_html=True,
    )

    # ── אפשרות מחיקת חודש מלא ──
    with st.expander("⚠️ מחיקת קבצי החודש כולו"):
        st.warning(f"זה ימחק את כל הקבצים בתיקייה {month_dir}.")
        col_d, _ = st.columns([1, 3])
        with col_d:
            if st.button("מחק את כל קבצי החודש", key="del_month",
                         type="secondary"):
                for f in month_dir.iterdir():
                    if f.is_file():
                        f.unlink()
                st.success("נמחק. רענן את הדף.")
                st.rerun()

    # ── 4. העלאת קבצים חדשים ──
    sec("העלה קבצים חדשים")
    st.caption("אם קובץ של אותו סוג כבר קיים - הוא יוחלף.")

    uploaded: dict[str, st.runtime.uploaded_file_manager.UploadedFile | None] = {}
    cols = st.columns(2)
    for i, (slot_key, slot) in enumerate(SLOTS.items()):
        with cols[i % 2]:
            up = st.file_uploader(
                f"{slot['label']}{' *' if slot['required'] else ''}",
                type=["xlsx", "xls"],
                key=f"up_{slot_key}_{project_id}_{month}",
            )
            uploaded[slot_key] = up

    any_uploaded = any(uploaded.values())
    save_label = "💾 שמור קבצים" + (
        f" ({sum(1 for u in uploaded.values() if u)} קבצים)" if any_uploaded else ""
    )
    rebuild = st.checkbox("בנה מחדש את מאסטר הנתונים אחרי השמירה (מומלץ)",
                          value=True, key="run_build")

    # ── בדיקת כפילויות SHA-256 ──
    import hashlib
    duplicates_warnings = []
    for slot_key, up in uploaded.items():
        if up is None:
            continue
        data = up.getbuffer().tobytes()
        new_hash = hashlib.sha256(data).hexdigest()
        old = _existing_file_for_slot(month_dir, SLOTS[slot_key]["keywords"])
        if old:
            try:
                old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
                if old_hash == new_hash:
                    duplicates_warnings.append(
                        f"⚠️ הקובץ '{up.name}' זהה בייטים-לבייטים ל-'{old.name}' "
                        f"שכבר נטען. לא צריך לטעון שוב."
                    )
            except Exception:
                pass
    if duplicates_warnings:
        for w in duplicates_warnings:
            st.warning(w)

    if st.button(save_label, type="primary", disabled=not any_uploaded,
                 use_container_width=True):
        saved = []
        from core import db
        for slot_key, up in uploaded.items():
            if up is None:
                continue
            slot = SLOTS[slot_key]
            # אם יש קובץ ישן עם slot זה - מחק אותו לפני שמירה
            old = _existing_file_for_slot(month_dir, slot["keywords"])
            if old and old.name != up.name:
                old.unlink()
            # שמור את הקובץ החדש בשם המקורי שלו
            target = month_dir / up.name
            with open(target, "wb") as fh:
                fh.write(up.getbuffer())
            saved.append(f"{slot['label']}: {up.name}")
            # רישום ל-audit
            try:
                db.log_event("file_import", {
                    "project_id": project_id, "month": month,
                    "file_type": slot_key, "file_name": up.name,
                    "size_bytes": len(up.getbuffer()),
                })
            except Exception:
                pass
        st.success("נשמר:\n" + "\n".join(f"  • {s}" for s in saved))

        if rebuild:
            with st.spinner("בונה מאסטר נתונים מחדש..."):
                master = build_master()
            st.success(f"מאסטר נבנה מחדש: {len(master):,} שורות. רענן את הפרויקט לראות.")
            # נקה cache של st.cache_data כך שהדשבורד יראה דאטה טריה
            st.cache_data.clear()
        st.rerun()


# ════════════════════════════════════════════════════════════════════
#  יבוא דוחות מצטברים (כרטסת/מאזן עד היום)
# ════════════════════════════════════════════════════════════════════

_LEDGER_LABEL = "כרטסת (תנועות הנהלת חשבונות)"
_BALANCE_LABEL = "מאזן בוחן (יתרות עד תאריך)"
_MODE_LABELS = {
    "add_new": "הוסף רק תנועות חדשות (מומלץ)",
    "replace_range": "החלף את כל הנתונים בטווח התאריכים של הקובץ",
    "check_only": "בדיקה בלבד — ללא שמירה",
}


def _parse_uploaded(up, loader) -> "object":
    """שומר קובץ שהועלה לקובץ זמני ומריץ עליו loader. מנקה אחריו."""
    import tempfile
    from pathlib import Path as _P
    suffix = _P(up.name).suffix or ".xlsx"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
            tf.write(up.getbuffer())
            tmp = tf.name
        return loader(tmp)
    finally:
        if tmp:
            try:
                _P(tmp).unlink()
            except Exception:
                pass


def _fmt_d(val) -> str:
    """תאריך → dd/mm/YYYY או '—'."""
    import pandas as pd
    ts = pd.to_datetime(val, errors="coerce")
    if pd.isna(ts):
        return "—"
    return ts.strftime("%d/%m/%Y")


def _show_he(df, mapping: dict) -> None:
    """משנה שמות עמודות לעברית ומציג דרך display_dataframe."""
    display_dataframe(df.rename(columns=mapping))


def _render_cumulative_import(projects: list[dict]) -> None:
    """ייבוא דוח מצטבר: כרטסת (תנועות) או מאזן (יתרות), עם dedup ותצוגה מקדימה."""
    from core import ledger_store, balance_store, db
    from core import chashbashevet_loader, balance_loader

    # ── 1. פרטי הדוח ──
    sec("1. פרטי הדוח")
    c1, c2 = st.columns([2, 1])
    with c1:
        names = [p["project_name"] for p in projects]
        pick = st.selectbox("פרויקט", names, key="cum_project")
        project = next(p for p in projects if p["project_name"] == pick)
        project_id = project["project_id"]
        project_name = project["project_name"]
    with c2:
        report_type = st.radio("סוג דוח", [_LEDGER_LABEL, _BALANCE_LABEL],
                               key="cum_rtype")

    c3, c4 = st.columns(2)
    with c3:
        from datetime import date as _date
        report_date = st.date_input("תאריך הדוח / עד תאריך", value=_date.today(),
                                    key="cum_rdate", format="DD/MM/YYYY")
    with c4:
        source = st.selectbox("מקור", ["חשבשבת", "ידני", "אחר"], key="cum_source")

    is_ledger = report_type == _LEDGER_LABEL

    # ── 2. העלאת קובץ ──
    sec("2. העלאת קובץ")
    st.caption("ניתן להעלות דוח מצטבר (לדוגמה כרטסת 01/01/2025 → היום). "
               "המערכת תשייך כל תנועה לחודש לפי תאריך התנועה.")
    up = st.file_uploader(
        f"קובץ {'כרטסת' if is_ledger else 'מאזן'} (xlsx/xls)",
        type=["xlsx", "xls"], key=f"cum_up_{project_id}_{is_ledger}",
    )
    if up is None:
        st.info("העלה קובץ כדי לראות תצוגה מקדימה.")
        return

    # ── 3. פענוח + תצוגה מקדימה ──
    sec("3. תצוגה מקדימה")
    if is_ledger:
        df = _parse_uploaded(up, chashbashevet_loader.load_chashbashevet)
        if df is None or df.empty:
            st.error("לא זוהו תנועות בקובץ. ודא שזו כרטסת חשבשבת תקינה.")
            return
        st.caption(f"זוהו {len(df):,} תנועות. הצגת 50 הראשונות:")
        prev = df[["date", "account_num", "account_name", "details",
                   "debit", "credit", "amount", "supplier"]].head(50).copy()
        _show_he(prev, {
            "date": "תאריך", "account_num": "חשבון", "account_name": "שם חשבון",
            "details": "פרטים", "debit": "חובה", "credit": "זכות",
            "amount": "סכום נטו", "supplier": "ספק"})
        _render_ledger_import_controls(
            project_id, project_name, df, up.name, report_date, source)
    else:
        df = _parse_uploaded(up, balance_loader.load_balance)
        if df is None or df.empty:
            st.error("לא זוהו שורות מאזן בקובץ. ודא שזה מאזן בוחן תקין.")
            return
        df = df.copy()
        df["account_type"] = df.apply(
            lambda r: balance_store.classify_account_type(
                r.get("account_num"), r.get("group", ""), r.get("account_name", "")),
            axis=1)
        st.caption(f"זוהו {len(df):,} חשבונות במאזן ליום {_fmt_d(report_date)}:")
        prev = df[["account_num", "account_name", "account_type",
                   "debit", "credit", "balance", "group"]].head(80).copy()
        _show_he(prev, {
            "account_num": "חשבון", "account_name": "שם חשבון",
            "account_type": "סוג חשבון", "debit": "יתרת חובה",
            "credit": "יתרת זכות", "balance": "יתרה נטו", "group": "קבוצה"})
        _render_balance_import_controls(
            project_id, project_name, df, up.name, report_date, source)


def _render_ledger_import_controls(project_id, project_name, df, file_name,
                                   report_date, source) -> None:
    """בקרות יבוא לכרטסת: בחירת מצב, ניתוח, אישור."""
    from core import ledger_store, db

    sec("4. ניתוח ובחירת אופן היבוא")
    mode_key = st.radio(
        "אופן היבוא",
        list(_MODE_LABELS.keys()),
        format_func=lambda k: _MODE_LABELS[k],
        key="cum_mode",
    )
    summary = ledger_store.analyze(project_id, df, mode_key)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("שורות בקובץ", f"{summary['rows_in_file']:,}")
    m2.metric("תנועות חדשות", f"{summary['new_count']:,}")
    m3.metric("כפילויות (ידולגו)", f"{summary['duplicate_count']:,}")
    m4.metric("תנועות שהשתנו", f"{summary['updated_count']:,}")

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("טווח תאריכים", f"{_fmt_d(summary['date_min'])} – {_fmt_d(summary['date_max'])}")
    m6.metric("חודשים בקובץ", f"{len(summary['months'])}")
    m7.metric('סה"כ חובה', format_currency(summary["debit_sum"]))
    m8.metric('סה"כ זכות', format_currency(summary["credit_sum"]))

    if summary["months"]:
        st.caption("חודשים מושפעים: " + ", ".join(summary["months"]))
    st.caption(f"מאגר לפני: {summary['store_before']:,} → אחרי: {summary['store_after']:,} תנועות")

    # ── אזהרות בקרה ──
    if summary["no_date_count"]:
        ins("amber", "⚠️", "תנועות ללא תאריך",
            f"{summary['no_date_count']} שורות ללא תאריך תקין — לא ישויכו לחודש ויידלגו.")
    if summary["updated_count"] and mode_key == "add_new":
        ins("amber", "🔁", "זוהו תנועות עם סכום שהשתנה",
            f"{summary['updated_count']} תנועות קיימות עם סכום שונה. במצב "
            "'הוסף רק חדשות' הן ייכנסו כתנועה נוספת. לתיקון רטרואקטיבי בחר "
            "'החלף את כל הנתונים בטווח התאריכים'.")

    is_check = mode_key == "check_only"
    label = "🔎 הרץ בדיקה" if is_check else "✅ אשר ויבא"
    if st.button(label, type="primary", use_container_width=True, key="cum_confirm"):
        if is_check:
            db.log_import(project_id, project_name, "ledger", file_name,
                          str(report_date), source, mode_key, summary, "checked")
            st.success("בדיקה הושלמה — לא בוצעה שמירה.")
            _post_import_summary(summary, "ledger", file_name, report_date, saved=False)
            return
        with st.spinner("שומר תנועות ובונה מאסטר מחדש..."):
            applied = ledger_store.apply_import(project_id, df, mode_key, file_name)
            db.log_import(project_id, project_name, "ledger", file_name,
                          str(report_date), source, mode_key, applied, "approved")
            build_master()
            st.cache_data.clear()
        st.success("היבוא הושלם והדשבורד עודכן.")
        _post_import_summary(applied, "ledger", file_name, report_date, saved=True)


def _render_balance_import_controls(project_id, project_name, df, file_name,
                                    report_date, source) -> None:
    """בקרות יבוא למאזן: שמירת snapshot לפי תאריך (בקרה בלבד, לא תנועות)."""
    from core import balance_store, db

    sec("4. שמירת תצלום מאזן")
    st.caption("המאזן נשמר כתצלום (snapshot) לפי תאריך דוח — לבקרה ויתרות "
               "עד-תאריך. הוא **אינו** נשמר כתנועות (כדי למנוע כפילות).")

    total_debit = float(df["debit"].sum())
    total_credit = float(df["credit"].sum())
    b1, b2, b3 = st.columns(3)
    b1.metric("חשבונות במאזן", f"{len(df):,}")
    b2.metric('סה"כ יתרת חובה', format_currency(total_debit))
    b3.metric('סה"כ יתרת זכות', format_currency(total_credit))
    gap = round(total_debit - total_credit, 2)
    if abs(gap) > 1:
        ins("amber", "⚠️", "אי-איזון במאזן",
            f"הפרש חובה/זכות: {format_currency(gap)}. מאזן בוחן תקין אמור להתאזן.")

    if st.button("💾 שמור תצלום מאזן", type="primary",
                 use_container_width=True, key="cum_bal_confirm"):
        n = balance_store.save_snapshot(project_id, df, report_date, file_name)
        summary = {
            "rows_in_file": len(df), "new_count": n, "duplicate_count": 0,
            "updated_count": 0, "months": [],
            "date_min": report_date, "date_max": report_date,
            "debit_sum": total_debit, "credit_sum": total_credit,
            "no_date_count": 0, "no_amount_count": 0,
            "store_before": 0, "store_after": n,
        }
        db.log_import(project_id, project_name, "balance", file_name,
                      str(report_date), source, "snapshot", summary, "approved")
        st.cache_data.clear()
        st.success(f"תצלום מאזן ליום {_fmt_d(report_date)} נשמר ({n} חשבונות).")
        _post_import_summary(summary, "balance", file_name, report_date, saved=True)


def _post_import_summary(summary, report_type, file_name, report_date, saved) -> None:
    """מסך סיכום אחרי יבוא (פריט 10 במפרט)."""
    rt_he = "כרטסת" if report_type == "ledger" else "מאזן בוחן"
    rows = [
        ("שם קובץ", file_name),
        ("סוג דוח", rt_he),
        ("תאריך דוח", _fmt_d(report_date)),
        ("שורות בקובץ", f"{summary.get('rows_in_file', 0):,}"),
        ("שורות חדשות", f"{summary.get('new_count', 0):,}"),
        ("כפילויות", f"{summary.get('duplicate_count', 0):,}"),
        ("שורות שגויות", f"{summary.get('no_date_count', 0) + summary.get('no_amount_count', 0):,}"),
        ("טווח תאריכים", f"{_fmt_d(summary.get('date_min'))} – {_fmt_d(summary.get('date_max'))}"),
        ("חודשים מושפעים", ", ".join(summary.get("months", [])) or "—"),
        ('סה"כ חובה', format_currency(summary.get("debit_sum", 0))),
        ('סה"כ זכות', format_currency(summary.get("credit_sum", 0))),
    ]
    cells = "".join(
        f'<tr><td style="padding:6px 10px;font-weight:600;color:var(--ink-soft)">{k}</td>'
        f'<td style="padding:6px 10px;color:var(--ink-strong);font-weight:700">{v}</td></tr>'
        for k, v in rows
    )
    badge = ("נשמר ✓" if saved else "בדיקה בלבד")
    st.markdown(
        f'<div style="border:1px solid var(--line);border-radius:10px;'
        f'overflow:hidden;margin-top:8px"><div style="padding:8px 12px;'
        f'background:linear-gradient(135deg,#F0FDF4,#fff);font-weight:800;'
        f'color:var(--ink-strong)">סיכום יבוא — {badge}</div>'
        f'<table style="width:100%;border-collapse:collapse">{cells}</table></div>',
        unsafe_allow_html=True,
    )


def _render_import_history(projects: list[dict]) -> None:
    """תצוגת היסטוריית יבוא (import_log)."""
    from core import db

    sec("היסטוריית יבוא")
    names = ["כל הפרויקטים"] + [p["project_name"] for p in projects]
    pick = st.selectbox("סינון לפי פרויקט", names, key="hist_project")
    pid = None
    if pick != "כל הפרויקטים":
        pid = next(p["project_id"] for p in projects if p["project_name"] == pick)

    if not hasattr(db, "import_history"):
        empty_state(icon="ti-history-off", title="היסטוריית היבוא אינה זמינה כעת",
                    body_html="המערכת מתעדכנת — נסה לרענן את הדף בעוד רגע.")
        return
    try:
        hist = db.import_history(pid)
    except Exception:
        logger.exception("import_history failed")
        empty_state(icon="ti-history-off", title="לא ניתן לטעון את היסטוריית היבוא",
                    body_html="אירעה שגיאה בקריאת ההיסטוריה. נסה לרענן את הדף.")
        return
    if hist is None or hist.empty:
        empty_state(icon="ti-history-off", title="אין עדיין היסטוריית יבוא",
                    body_html="לאחר יבוא דוח ראשון, הוא יופיע כאן.")
        return

    rt_map = {"ledger": "כרטסת", "balance": "מאזן"}
    st_map = {"approved": "אושר ויובא", "checked": "בדיקה בלבד", "failed": "נכשל"}
    disp = hist[["timestamp", "project_name", "report_type", "file_name",
                 "report_date", "source", "mode", "rows_in_file", "new_rows",
                 "duplicate_rows", "updated_rows", "months_affected", "status"]].copy()
    disp["report_type"] = disp["report_type"].map(rt_map).fillna(disp["report_type"])
    disp["status"] = disp["status"].map(st_map).fillna(disp["status"])
    disp["mode"] = disp["mode"].map(_MODE_LABELS).fillna(disp["mode"])
    _show_he(disp, {
        "timestamp": "מועד העלאה", "project_name": "פרויקט",
        "report_type": "סוג דוח", "file_name": "קובץ",
        "report_date": "תאריך דוח", "source": "מקור", "mode": "אופן",
        "rows_in_file": "שורות בקובץ", "new_rows": "חדשות",
        "duplicate_rows": "כפילויות", "updated_rows": "עודכנו",
        "months_affected": "חודשים", "status": "סטטוס"})
