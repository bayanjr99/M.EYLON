"""מסך ייבוא נתונים: העלאת קבצי חודש לפרויקט.

זרימה:
    1. בחירת פרויקט + חודש (MM-YYYY)
    2. הצגת קבצים קיימים (עם אפשרות מחיקה)
    3. העלאת קבצים חדשים (כרטיס/מאזן/סולר/שעות)
    4. שמירה לתיקיית הפרויקט/חודש
    5. הפעלת build_master() אוטומטית כדי לרענן את המאסטר
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import streamlit as st

from pipeline import PROJECTS_ROOT, build_master, list_available_months
from ui.components import empty_state, ins, sec


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
    """המסך הראשי לייבוא נתונים."""
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
                ייבוא נתוני חודש</div>
                <div style="font-size:11px;color:var(--ink-soft);margin-top:2px">
                  העלה קבצי כרטיס הנהלה / מאזן / סולר / שעות לפרויקט וחודש
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
