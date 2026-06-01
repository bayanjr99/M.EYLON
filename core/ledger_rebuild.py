"""בנייה-מחדש בטוחה של מאגר התנועות לפי תאריך המסמך (document_date).

רקע
----
מאגר התנועות (``ledger_store``) קובע את חודש התנועה ואת ה-row_hash לפי
העמודה הקנונית ``date``. בעבר ``date`` נגזר מתאריך הערך (עמודה J); כיום
הוא נגזר בעדיפות מתאריך המסמך/אסמכתא (עמודה I), ורק אם חסר — מתאריך הערך.

לכן שורות שנשמרו במאגר *לפני* השינוי עלולות להיות משויכות לחודש הלא-נכון,
ויבוא חוזר של אותו קובץ היה יוצר כפילויות (row_hash שונה). מודול זה מבצע
בנייה-מחדש *בטוחה* של המאגר הקיים — בלי יבוא חוזר ובלי איבוד נתונים:

עקרונות בטיחות (לפי דרישות המשתמש)
--------------------------------
1. **גיבוי לפני כל שינוי** — עותק חתום-זמן של ``_ledger_store.parquet``
   (וגם של ``master.parquet`` דרך ``storage.backup_database``).
2. **לא מוחקים נתונים** — הבנייה-מחדש מחשבת מחדש את התאריך הקנוני, החודש
   וה-hash, ואז מאחדת כפילויות (אותו row_hash) בלבד. שורות לא נמחקות
   אלא מתמזגות.
3. **תצוגה מקד��מה (dry-run)** — ``analyze_rebuild`` מראה *מה ישתנה*
   (כמה שורות יעברו חודש, כמה ללא תאריך מסמך, כמה כפילויות יתמזגו) בלי
   לכתוב דבר.
4. **חודשים מבוססי document_date** — התאריך הקנוני נקבע כ:
   document_date אם תקין, אחרת value_date, אחרת ה-date הקיים.

זרימה
-----
    analyze_rebuild(pid)            → תצוגה מקדימה (ללא כתיבה)
    apply_rebuild(pid)             → גיבוי → בניית מאגר מחדש → שמירה
    (הקורא מריץ build_master() אחרי כן כדי לרענן את המאסטר)
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import ledger_store

logger = logging.getLogger(__name__)


# ── חישוב התאריך הקנוני (document_date → value_date → date) ──────
def _canonical_dates(store: pd.DataFrame) -> pd.Series:
    """מחזיר Series של התאריך הקנוני לכל שורה לפי עדיפות document_date.

    document_date (עמודה I) אם תקין → אחרת value_date (עמודה J) → אחרת
    ה-date הקיים במאגר (תאימות לאחור לשורות ישנות ללא document_date).
    """
    n = len(store)
    doc = (pd.to_datetime(store["document_date"], errors="coerce")
           if "document_date" in store.columns
           else pd.Series([pd.NaT] * n, index=store.index))
    val = (pd.to_datetime(store["value_date"], errors="coerce")
           if "value_date" in store.columns
           else pd.Series([pd.NaT] * n, index=store.index))
    cur = (pd.to_datetime(store["date"], errors="coerce")
           if "date" in store.columns
           else pd.Series([pd.NaT] * n, index=store.index))
    canonical = doc.where(doc.notna(), val)
    canonical = canonical.where(canonical.notna(), cur)
    return canonical


def _month_str(s: pd.Series) -> pd.Series:
    """ממיר Series של תאריכים למחרוזת חודש MM-YYYY (NaT → None)."""
    dt = pd.to_datetime(s, errors="coerce")
    return dt.dt.strftime("%m-%Y").where(dt.notna(), None)


def _empty_preview() -> dict:
    return {
        "has_store": False, "rows": 0, "has_document_date": False,
        "rows_moved_month": 0, "rows_no_document_date": 0,
        "duplicates_collapsed": 0, "rows_after": 0,
        "months_before": [], "months_after": [], "month_moves": [],
        "needs_rebuild": False,
    }


def analyze_rebuild(project_id: str) -> dict:
    """תצוגה מקדימה (dry-run) של בניית המאגר מחדש — ללא כתיבה.

    Returns:
        dict עם: has_store, rows, has_document_date, rows_moved_month,
        rows_no_document_date, duplicates_collapsed, rows_after,
        months_before, months_after, month_moves [{from,to,count}], needs_rebuild.
    """
    preview = _empty_preview()
    store = ledger_store.load_store(project_id)
    if store is None or store.empty:
        return preview

    preview["has_store"] = True
    preview["rows"] = len(store)
    preview["has_document_date"] = "document_date" in store.columns

    old_month = (store["month"].astype("object")
                 if "month" in store.columns
                 else pd.Series([None] * len(store), index=store.index))
    new_date = _canonical_dates(store)
    new_month = _month_str(new_date)

    # כמה שורות חסרות document_date תקין (ייפול ל-value/date)
    if "document_date" in store.columns:
        doc = pd.to_datetime(store["document_date"], errors="coerce")
        preview["rows_no_document_date"] = int(doc.isna().sum())
    else:
        preview["rows_no_document_date"] = len(store)

    # שורות שמשנות חודש
    om = old_month.fillna("").astype(str)
    nm = new_month.fillna("").astype(str)
    moved_mask = om != nm
    preview["rows_moved_month"] = int(moved_mask.sum())

    # פירוט מעברי חודש (from → to : count)
    if moved_mask.any():
        moves = (pd.DataFrame({"from": om[moved_mask], "to": nm[moved_mask]})
                 .value_counts().reset_index(name="count"))
        preview["month_moves"] = [
            {"from": r["from"] or "(ללא)", "to": r["to"] or "(ללא)",
             "count": int(r["count"])}
            for _, r in moves.iterrows()
        ]

    preview["months_before"] = sorted(x for x in om.unique() if x)
    preview["months_after"] = sorted(x for x in nm.unique() if x)

    # כפילויות שיתמזגו אחרי חישוב מחדש של row_hash
    rebuilt = _rebuild_frame(store, new_date)
    if "row_hash" in rebuilt.columns:
        preview["rows_after"] = int(rebuilt["row_hash"].nunique())
        preview["duplicates_collapsed"] = len(rebuilt) - preview["rows_after"]
    else:
        preview["rows_after"] = len(rebuilt)

    preview["needs_rebuild"] = bool(
        preview["rows_moved_month"] or preview["duplicates_collapsed"])
    return preview


def _rebuild_frame(store: pd.DataFrame, new_date: pd.Series) -> pd.DataFrame:
    """בונה DataFrame מחדש: מציב את התאריך הקנוני ומחשב hash/month מחדש."""
    rebuilt = store.copy()
    rebuilt["date"] = new_date.values
    # add_hashes מחשב row_hash/key_hash/month מחדש לפי date/account_num/...
    rebuilt = ledger_store.add_hashes(rebuilt)
    return rebuilt


# ── גיבוי + ביצוע ───────────────────────────────────────────────
def _backup_store(project_id: str) -> str | None:
    """מגבה את קובץ מאגר התנועות לתיקיית backups של הפרויקט. None אם אין."""
    from pipeline import PROJECTS_ROOT
    src = PROJECTS_ROOT / project_id / "_ledger_store.parquet"
    if not src.exists():
        return None
    backups = PROJECTS_ROOT / project_id / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backups / f"_ledger_store_{ts}.parquet"
    shutil.copy2(src, dst)
    logger.info("Backed up ledger store %s → %s", src, dst)
    return str(dst)


def apply_rebuild(project_id: str, do_backup: bool = True) -> dict:
    """מבצע בנייה-מחדש בטוחה של המאגר: גיבוי → חישוב מחדש → שמירה.

    **לא מריץ build_master()** — הקורא אחראי לרענן את המאסטר אחרי כן
    (כדי שניתן יהיה לגבות/לרענן פעם אחת אחרי מספר פרויקטים).

    Returns:
        dict: התצוגה המקדימה + applied=True/False, backup_store,
        backup_master (dict), error (אופציונלי).
    """
    result = analyze_rebuild(project_id)
    result["applied"] = False
    if not result["has_store"]:
        result["error"] = "אין מאגר תנועות לפרויקט זה."
        return result

    try:
        # ── גיבוי לפני כל שינוי (חובה) ──
        if do_backup:
            result["backup_store"] = _backup_store(project_id)
            try:
                from core import storage
                bk = storage.backup_database(
                    suffix=f"prerebuild_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                result["backup_master"] = {k: str(v) for k, v in bk.items()}
            except Exception as e:  # גיבוי מאסטר לא חוסם אם נכשל
                logger.warning("master backup before rebuild failed: %s", e)
                result["backup_master"] = {}

        store = ledger_store.load_store(project_id)
        new_date = _canonical_dates(store)
        rebuilt = _rebuild_frame(store, new_date)
        # מיזוג כפילויות (אותו row_hash) — keep last, לא מוחק מידע ייחודי
        if "row_hash" in rebuilt.columns:
            rebuilt = rebuilt.drop_duplicates(subset=["row_hash"], keep="last")
        rebuilt = rebuilt.reset_index(drop=True)
        ledger_store.save_store(project_id, rebuilt)
        result["rows_after"] = len(rebuilt)
        result["applied"] = True
        logger.info("Rebuilt ledger store %s: %d → %d rows",
                    project_id, result["rows"], len(rebuilt))
    except Exception as e:
        logger.exception("apply_rebuild failed for %s: %s", project_id, e)
        result["error"] = str(e)
    return result
