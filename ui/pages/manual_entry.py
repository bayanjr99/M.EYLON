"""מסך הזנת נתונים ידנית בסגנון אקסל — סולר ושעות עבודה.

זרימה ב-4 שלבים:
    1. הדבקה   — הדבק טבלה מאקסל (TSV) לתיבת טקסט.
    2. מיפוי   — המערכת מזהה עמודות אוטומטית; ניתן לתקן ידנית.
    3. בדיקה   — עריכה אחרונה + בדיקת שגיאות שורה-שורה.
    4. שמירה   — שמירת שורות תקינות בלבד (עם זיהוי כפילויות).

הנתונים נשמרים ב-manual_store ומשם זורמים ל-master.parquet
(pipeline.aggregate_manual_*) — כך הם משפיעים על כל הטאבים והגרפים,
ממוינים לחודש לפי תאריך השורה.
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

_UNMAPPED = "— לא ממופה —"


# ── עזרי המרה ─────────────────────────────────────────────────
def _parse_tsv_raw(text: str) -> pd.DataFrame | None:
    """מפרק טקסט מודבק (TAB + שורות) ל-DataFrame מיקומי (עמודות 0..n)."""
    if not text or not text.strip():
        return None
    rows = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip() == "":
            continue
        rows.append(line.split("\t"))
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [None] * (width - len(r)) for r in rows]
    return pd.DataFrame(rows, columns=list(range(width)))


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


def _column_config(kind: str) -> dict:
    """בונה column_config ל-st.data_editor לפי הגדרת העמודות."""
    labels = manual_store.column_labels(kind)
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
        else:  # text / select — טקסט חופשי (גמיש להדבקה)
            cfg[key] = st.column_config.TextColumn(label)
    return cfg


def _step_bar(active: int) -> None:
    """פס שלבים: 1 הדבקה · 2 מיפוי · 3 בדיקה · 4 שמירה."""
    steps = ["1. הדבקה", "2. מיפוי עמודות", "3. בדיקה", "4. שמירה"]
    chips = []
    for i, name in enumerate(steps, start=1):
        if i == active:
            bg, col, bd = "var(--brand-primary)", "#FFFFFF", "var(--brand-primary)"
        elif i < active:
            bg, col, bd = "#ECFDF5", "#0F6E56", "#A7F3D0"
        else:
            bg, col, bd = "#F8FAFC", "#94A3B8", "#E2E8F0"
        chips.append(
            f'<span style="background:{bg};color:{col};border:1px solid {bd};'
            f'border-radius:8px;padding:4px 12px;font-size:12px;font-weight:700;'
            f'margin-left:6px">{name}</span>')
    st.markdown(
        f'<div style="display:flex;flex-direction:row-reverse;justify-content:'
        f'flex-end;gap:2px;margin:4px 0 12px">{"".join(chips)}</div>',
        unsafe_allow_html=True)


# ── תת-טאב לכל סוג דוח ─────────────────────────────────────────
def _render_kind(kind: str, projects: list[dict]) -> None:
    """מצייר את מסך ההזנה לסוג דוח בודד (solar / hours)."""
    from core import db

    labels = manual_store.column_labels(kind)
    keys = manual_store.column_keys(kind)

    # ── מפתחות state ──
    base = f"man_{kind}"
    raw_key = f"{base}_raw"
    hdr_key = f"{base}_hdr"
    map_key = f"{base}_map"
    seed_key = f"{base}_seed"
    rev_key = f"{base}_rev"
    rev = st.session_state.get(rev_key, 0)

    # ── 1. פרויקט + חודש יעד ──
    c1, c2 = st.columns([2, 1])
    with c1:
        names = [p["project_name"] for p in projects]
        pick = st.selectbox("פרויקט", names, key=f"{base}_proj")
        project = next(p for p in projects if p["project_name"] == pick)
        project_id = project["project_id"]
        project_name = project["project_name"]
    with c2:
        month_date = st.date_input("חודש יעד (להחלפת חודש)", value=_date.today(),
                                   key=f"{base}_month", format="DD/MM/YYYY")
        target_month = month_date.strftime("%m-%Y")

    existing = manual_store.load_store(project_id, kind)
    st.caption(f"במאגר כעת: {len(existing):,} שורות · כל שורה משויכת לחודש לפי "
               "התאריך שבה — אין צורך למלא חודש בכל שורה.")

    raw = st.session_state.get(raw_key)
    have_raw = isinstance(raw, pd.DataFrame) and not raw.empty
    have_seed = isinstance(st.session_state.get(seed_key), pd.DataFrame)

    # ════ שלב 1 — הדבקה ════
    if not have_seed:
        _step_bar(2 if have_raw else 1)
        sec("1. הדבקת נתונים מאקסל")
        st.caption("העתק את הטבלה מאקסל (עם או בלי שורת כותרת) והדבק כאן. "
                   "המערכת תזהה את העמודות אוטומטית בשלב הבא.")
        tsv = st.text_area("הדבק כאן נתונים מאקסל", height=160,
                           key=f"{base}_tsv_{rev}",
                           placeholder="הדבק כאן (Ctrl+V) — עמודות מופרדות ב-Tab")
        pc1, pc2 = st.columns([1, 3])
        with pc1:
            if st.button("📥 פרק נתונים", type="primary",
                         use_container_width=True, key=f"{base}_parse"):
                parsed = _parse_tsv_raw(tsv)
                if parsed is None:
                    st.warning("לא זוהו שורות בטקסט שהודבק.")
                else:
                    st.session_state[raw_key] = parsed
                    hdr = manual_store.detect_header(kind, parsed)
                    st.session_state[hdr_key] = hdr
                    header_vals = parsed.iloc[0].tolist() if hdr else None
                    st.session_state[map_key] = manual_store.guess_mapping(kind, header_vals)
                    st.rerun()

        if not have_raw:
            with st.expander("📝 או: התחל מטבלה ריקה (הקלדה ידנית)", expanded=False):
                if st.button("פתח טבלה ריקה", key=f"{base}_blank"):
                    blank = manual_store.empty_frame(kind).reindex(range(10)).reset_index(drop=True)
                    st.session_state[seed_key] = blank
                    st.session_state[rev_key] = rev + 1
                    st.rerun()
            return

        # ════ שלב 2 — מיפוי עמודות ════
        sec("2. מיפוי עמודות")
        has_header = bool(st.session_state.get(hdr_key))
        st.caption(("זוהתה שורת כותרת — המערכת מיפתה את העמודות אוטומטית. "
                    if has_header else
                    "לא זוהתה כותרת — בדוק את המיפוי לפי סדר העמודות. ") +
                   "תקן במידת הצורך.")

        ncols = raw.shape[1]
        body_preview = raw.iloc[1:] if has_header and len(raw) > 1 else raw
        # אפשרויות לכל בורר: מספר עמודה + דוגמה מהשורה הראשונה בגוף
        sample = body_preview.iloc[0].tolist() if len(body_preview) else [None] * ncols

        def _col_label(i: int) -> str:
            head = ""
            if has_header:
                head = manual_store._norm_text(raw.iloc[0, i])
            ex = manual_store._norm_text(sample[i]) if i < len(sample) else ""
            txt = f"עמודה {i + 1}"
            if head:
                txt += f" · {head}"
            elif ex:
                txt += f" · דוגמה: {ex[:20]}"
            return txt

        col_options = [_UNMAPPED] + [_col_label(i) for i in range(ncols)]
        mapping = dict(st.session_state.get(map_key, {}))
        # שלוש עמודות בוררים כדי לחסוך מקום
        mcols = st.columns(3)
        new_mapping: dict[str, int | None] = {}
        for j, field in enumerate(keys):
            cur = mapping.get(field)
            default_idx = (cur + 1) if (cur is not None and cur < ncols) else 0
            with mcols[j % 3]:
                sel = st.selectbox(labels[field], col_options, index=default_idx,
                                   key=f"{base}_map_{field}_{rev}")
            new_mapping[field] = None if sel == _UNMAPPED else col_options.index(sel) - 1
        st.session_state[map_key] = new_mapping

        # תצוגה מקדימה של 10 שורות לפי המיפוי הנוכחי
        mapped = manual_store.apply_mapping(kind, raw, new_mapping, has_header)
        prepared_prev = manual_store.prepare_incoming(kind, mapped)
        mapped_fields = [labels[f] for f, idx in new_mapping.items() if idx is not None]
        unmapped_fields = [labels[f] for f, idx in new_mapping.items() if idx is None]
        st.markdown(f"**זוהו {len(mapped_fields)} עמודות:** " +
                    ", ".join(mapped_fields) if mapped_fields else "**לא מופו עמודות**")
        if unmapped_fields:
            st.caption("לא מופו (יישארו ריקים): " + ", ".join(unmapped_fields))
        st.caption(f"סה\"כ {len(prepared_prev):,} שורות נתונים (ללא שורות ריקות). "
                   "תצוגה מקדימה של 10 הראשונות:")
        if not prepared_prev.empty:
            prev = prepared_prev[keys].head(10).rename(columns=labels)
            st.dataframe(prev, use_container_width=True, hide_index=True)

        bc1, bc2, _ = st.columns([1, 1, 2])
        with bc1:
            if st.button("✓ החל מיפוי והמשך", type="primary",
                         use_container_width=True, key=f"{base}_applymap"):
                if prepared_prev.empty:
                    st.warning("אין שורות נתונים לאחר המיפוי.")
                else:
                    seed = prepared_prev[keys].reset_index(drop=True)
                    st.session_state[seed_key] = manual_store._coerce_types(kind, seed)
                    st.session_state[rev_key] = rev + 1
                    st.rerun()
        with bc2:
            if st.button("🧹 התחל מחדש", use_container_width=True,
                         key=f"{base}_reset_map"):
                _reset_state(base)
                st.rerun()
        return

    # ════ שלבים 3-4 — עריכה, בדיקה, שמירה ════
    _step_bar(3)
    seed = st.session_state.get(seed_key)
    sec("3. בדיקה ועריכה אחרונה")
    st.caption("ערוך תאים, הוסף או מחק שורות לפי הצורך. הדבקה נוספת מאקסל "
               "אפשרית גם כאן (תא בודד או טווח).")
    edited = st.data_editor(
        seed, key=f"{base}_editor_{rev}", num_rows="dynamic",
        use_container_width=True, column_config=_column_config(kind),
        hide_index=True)

    rc1, rc2, rc3 = st.columns([1, 1, 1])
    with rc1:
        if st.button("↩ חזרה למיפוי", use_container_width=True,
                     key=f"{base}_back_map"):
            st.session_state.pop(seed_key, None)
            st.session_state[rev_key] = rev + 1
            st.rerun()
    with rc2:
        xls = _to_excel_bytes(kind, edited)
        st.download_button("📤 ייצא לאקסל", data=xls,
                           file_name=f"{kind}_{project_id}_{target_month}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"{base}_export", use_container_width=True,
                           disabled=not xls)
    with rc3:
        if st.button("🧹 התחל מחדש", use_container_width=True,
                     key=f"{base}_reset_all"):
            _reset_state(base)
            st.rerun()

    # ── מצב שמירה + כפתורי בדיקה/שמירה צמודים ──
    sec("4. אופן שמירה")
    mode_key = st.radio("אופן השמירה", list(_MODE_LABELS.keys()),
                        format_func=lambda k: _MODE_LABELS[k],
                        key=f"{base}_mode", horizontal=True)

    summary = manual_store.analyze(project_id, kind, edited, mode_key, target_month)
    prepared = manual_store.prepare_incoming(kind, edited)

    if summary["rows_in_file"] == 0:
        st.info("הטבלה ריקה — אין מה לבדוק או לשמור.")
        return

    _render_summary(kind, summary, mode_key)

    # ── טבלת אבחון שורות לא תקינות ──
    diag = manual_store.row_diagnostics(kind, prepared)
    bad = diag[diag["סטטוס"] == "שגיאה"]
    if not bad.empty:
        with st.expander(f"⚠️ פירוט {len(bad)} שורות עם שגיאה (לחץ להצגה)",
                         expanded=summary["valid_count"] == 0):
            st.dataframe(bad[["שורה", "תאריך", "בעיות"]],
                         use_container_width=True, hide_index=True)
            err_csv = bad.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ הורד קובץ שגיאות (CSV)", data=err_csv,
                               file_name=f"errors_{kind}_{target_month}.csv",
                               mime="text/csv", key=f"{base}_errcsv")

    # ── שמירה ──
    can_save = summary["valid_count"] > 0 and mode_key != "check_only"
    if st.button(f"✅ שמור {summary['valid_count']} שורות תקינות",
                 type="primary", use_container_width=True,
                 disabled=not can_save, key=f"{base}_save"):
        with st.spinner("שומר נתונים ובונה מאסטר מחדש..."):
            applied = manual_store.apply_import(
                project_id, kind, edited, mode_key,
                source_file="הזנה ידנית", target_month=target_month)
            try:
                db.log_import(project_id, project_name, f"manual_{kind}",
                              "הזנה ידנית", target_month, "ידני", mode_key,
                              applied, "approved")
            except Exception as e:
                logger.warning("log_import failed (non-fatal): %s", e)
            build_master()
            st.cache_data.clear()
        st.success(f"נשמרו {applied['valid_count']:,} שורות תקינות — הדשבורד עודכן.")
        _reset_state(base)


def _reset_state(base: str) -> None:
    """מנקה את כל ה-state של תת-הטאב (חוזר לשלב ההדבקה)."""
    rev = st.session_state.get(f"{base}_rev", 0)
    for suffix in ("_raw", "_hdr", "_map", "_seed"):
        st.session_state.pop(f"{base}{suffix}", None)
    st.session_state[f"{base}_rev"] = rev + 1


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

    if summary["valid_count"] == 0 and summary["error_count"]:
        ins("red", "⛔", "אין שורות תקינות לשמירה",
            "כל השורות חסרות תאריך או שדה חובה. ודא שעמודת התאריך מופתה נכון "
            "(חזור למיפוי) ושיש כמות ליטרים או סכום בכל שורה.")
    elif summary["error_count"]:
        ins("amber", "⚠️", f"{summary['error_count']} שורות לא תקינות יידלגו",
            "ראה פירוט למטה. ניתן לשמור את השורות התקינות בלבד.")
    if summary["duplicate_count"]:
        ins("blue", "🔁", "נמצאו שורות שכבר קיימות במערכת",
            f"{summary['duplicate_count']} שורות זהות כבר במאגר — יידולגו "
            "במצב 'הוסף רק חדשות'.")
    if summary["updated_count"] and mode_key == "add_new":
        ins("amber", "✏️", "שורות עם ערכים שהשתנו",
            f"{summary['updated_count']} שורות עם אותו מפתח אך ערכים שונים. "
            "במצב 'הוסף רק חדשות' הן ייכנסו כשורה נוספת — לעדכון בחר "
            "'עדכן שורות קיימות'.")


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
                  הדבק נתוני סולר/שעות מאקסל — זיהוי עמודות אוטומטי, בדיקת
                  שגיאות, ושמירה שמתעדכנת בכל הטאבים לפי תאריך השורה
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
