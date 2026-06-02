"""אחסון ענן קבוע להזנות ידניות (סולר/שעות) — Neon Postgres.

מטרה
----
על Streamlit Cloud מערכת הקבצים זמנית — קבצים שנכתבים שם נמחקים ב-
restart/redeploy. מודול זה שומר את ההזנות הידניות במסד נתונים קבוע
(Neon Postgres) כדי שהן ישרדו. הקובץ המקומי (parquet/xlsx) נשמר במקביל
כגיבוי.

עקרונות בטיחות (לפי דרישות המשתמש)
--------------------------------
1. דריסה (replace_month) ועדכון (update_existing) מתבצעים DELETE+INSERT
   בתוך *transaction* אחת — אם יש כשל באמצע, שום דבר לא נמחק.
2. אחרי כל שמירה מתבצעת קריאה חוזרת מ-Neon לאימות שהשורות אכן נכתבו —
   רק אז מסומן ``neon_verified_ok``.
3. כל שורה נשמרת עם ``raw_payload`` (JSONB) — התוכן המלא של השורה, כך
   ששינוי עתידי במבנה העמודות לא יאבד מידע מקורי.
4. כל שמירה מקבלת ``batch_id`` ונרשמת ל-``manual_import_log``.
5. אם NEON_DATABASE_URL לא מוגדר/לא זמין — המערכת לא קורסת: מחזירים
   ערכי ברירת-מחדל בטוחים, והמערכת עובדת במצב מקומי בלבד.

מחרוזת החיבור נקראת מ-Streamlit Secrets (``NEON_DATABASE_URL``) או
ממשתנה הסביבה באותו שם. *לעולם* לא נשמרת בקוד או ב-git.

טבלאות
------
``manual_entries``  — שורה לכל הזנה (PK = row_hash, dedup מובנה).
``manual_import_log`` — שורה לכל שמירה (batch_id, מתי, כמה, סטטוס).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime

import pandas as pd

from core import manual_store

logger = logging.getLogger(__name__)

_SECRET_KEY = "NEON_DATABASE_URL"


# ── מחרוזת חיבור + זמינות ──────────────────────────────────────
def _conn_str() -> str | None:
    """מחזיר את מחרוזת החיבור ל-Neon (env או Streamlit secrets), או None.

    סדר עדיפויות: משתנה סביבה → st.secrets. לעולם לא מקודד בקוד.
    """
    val = os.environ.get(_SECRET_KEY)
    if val:
        return val.strip() or None
    try:  # st.secrets זמין רק בהקשר Streamlit; בסקריפטים — try/except
        import streamlit as st
        if _SECRET_KEY in st.secrets:
            return str(st.secrets[_SECRET_KEY]).strip() or None
    except Exception:
        pass
    return None


def is_configured() -> bool:
    """האם הוגדרה מחרוזת חיבור ל-Neon (זול — לא פותח חיבור)."""
    return bool(_conn_str())


def _connect(timeout: int = 15):
    """פותח חיבור psycopg ל-Neon. זורק אם psycopg חסר או החיבור נכשל."""
    import psycopg  # ייבוא עצל — לא נדרש כשאין Neon
    dsn = _conn_str()
    if not dsn:
        raise RuntimeError("NEON_DATABASE_URL לא מוגדר.")
    return psycopg.connect(dsn, connect_timeout=timeout)


def is_available() -> bool:
    """בדיקה אמיתית: גם מוגדר וגם ניתן להתחבר (פותח חיבור קצר)."""
    if not is_configured():
        return False
    try:
        with _connect(timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as e:
        logger.warning("Neon not available: %s", e)
        return False


# ── סכמה ───────────────────────────────────────────────────────
def _ensure_schema(conn) -> None:
    """יוצר את הטבלאות + אינדקס אם אינם קיימים (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_entries (
                row_hash    TEXT PRIMARY KEY,
                key_hash    TEXT,
                kind        TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                month       TEXT,
                entry_date  DATE,
                import_date TIMESTAMPTZ DEFAULT now(),
                source_file TEXT,
                batch_id    UUID,
                raw_payload JSONB
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_manual_entries_proj_kind_month
            ON manual_entries (project_id, kind, month)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_import_log (
                batch_id        UUID PRIMARY KEY,
                ts              TIMESTAMPTZ DEFAULT now(),
                project_id      TEXT,
                project_name    TEXT,
                kind            TEXT,
                month           TEXT,
                mode            TEXT,
                rows_saved      INT,
                new_count       INT,
                duplicate_count INT,
                updated_count   INT,
                store_after     INT,
                status          TEXT
            )
            """
        )


def ensure_schema() -> bool:
    """מוודא שהסכמה קיימת ב-Neon (לשימוש סקריפט מיגרציה). False אם אין חיבור."""
    if not is_configured():
        return False
    try:
        with _connect() as conn:
            _ensure_schema(conn)
        return True
    except Exception as e:
        logger.exception("ensure_schema failed: %s", e)
        return False


# ── עזרי המרה ל-JSON / DB ──────────────────────────────────────
def _json_safe(v):
    """ממיר ערך לטיפוס שניתן לאחסון ב-JSON (None/מספר/מחרוזת)."""
    try:
        if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar → python native
        try:
            return v.item()
        except Exception:
            pass
    return v


def _date_or_none(v):
    """ממיר ערך לתאריך python (date) או None."""
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


# ── שמירה (transactional + read-back) ──────────────────────────
def save_entries(project_id: str, kind: str, valid: pd.DataFrame,
                 mode: str = "add_new", target_month: str | None = None,
                 source_file: str = "", project_name: str = "") -> dict:
    """שומר שורות תקינות ל-Neon ב-transaction, ומאמת בקריאה חוזרת.

    Args:
        valid: DataFrame של שורות תקינות (אחרי prepare+validate) — חייב
               להכיל row_hash, key_hash, month + עמודות ה-kind.
        mode: add_new / update_existing / replace_month.
        target_month: לחודש דריסה ספציפי (replace_month).

    Returns:
        dict: neon_saved, neon_verified_rows, neon_verified_ok, batch_id,
              neon_store_after, error (אופציונלי).
    """
    summary = {
        "neon_saved": False, "neon_verified_rows": 0,
        "neon_verified_ok": False, "batch_id": None, "neon_store_after": 0,
    }
    if valid is None or valid.empty or not is_configured():
        return summary

    batch_id = str(uuid.uuid4())
    field_keys = manual_store.column_keys(kind)
    records: list[dict] = []
    for _, r in valid.iterrows():
        payload = {k: _json_safe(r.get(k)) for k in field_keys}
        records.append({
            "row_hash": str(r.get("row_hash")),
            "key_hash": str(r.get("key_hash")),
            "month": (None if pd.isna(r.get("month")) else str(r.get("month"))),
            "entry_date": _date_or_none(r.get("date")),
            "payload": payload,
        })
    row_hashes = [rec["row_hash"] for rec in records]
    key_hashes = sorted({rec["key_hash"] for rec in records})
    months = sorted({rec["month"] for rec in records if rec["month"]})
    src = source_file or "הזנה ידנית"

    try:
        from psycopg.types.json import Jsonb
        with _connect() as conn:
            _ensure_schema(conn)
            # ── store_before ──
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM manual_entries "
                    "WHERE project_id=%s AND kind=%s",
                    (project_id, kind))
                store_before = int(cur.fetchone()[0])

            # ── DELETE + INSERT באותה transaction (אטומי) ──
            with conn.transaction():
                with conn.cursor() as cur:
                    if mode == "replace_month":
                        del_months = [target_month] if target_month else months
                        if del_months:
                            cur.execute(
                                "DELETE FROM manual_entries WHERE project_id=%s "
                                "AND kind=%s AND month = ANY(%s)",
                                (project_id, kind, del_months))
                    elif mode == "update_existing":
                        if key_hashes:
                            cur.execute(
                                "DELETE FROM manual_entries WHERE project_id=%s "
                                "AND kind=%s AND key_hash = ANY(%s)",
                                (project_id, kind, key_hashes))
                    for rec in records:
                        cur.execute(
                            "INSERT INTO manual_entries "
                            "(row_hash, key_hash, kind, project_id, month, "
                            " entry_date, source_file, batch_id, raw_payload) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT (row_hash) DO NOTHING",
                            (rec["row_hash"], rec["key_hash"], kind, project_id,
                             rec["month"], rec["entry_date"], src, batch_id,
                             Jsonb(rec["payload"])))
            # ── read-back אחרי commit: כל row_hash מצוי? ──
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM manual_entries WHERE row_hash = ANY(%s)",
                    (row_hashes,))
                present = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT count(*) FROM manual_entries "
                    "WHERE project_id=%s AND kind=%s",
                    (project_id, kind))
                store_after = int(cur.fetchone()[0])

            verified_ok = present == len(set(row_hashes))
            new_count = max(store_after - store_before, 0)
            dup_count = max(len(records) - new_count, 0) if mode == "add_new" else 0
            status = "approved" if verified_ok else "failed"

            # ── לוג יבוא (auxiliary) ──
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO manual_import_log "
                        "(batch_id, project_id, project_name, kind, month, mode, "
                        " rows_saved, new_count, duplicate_count, updated_count, "
                        " store_after, status) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (batch_id) DO NOTHING",
                        (batch_id, project_id, project_name, kind,
                         ", ".join(months), mode, len(records), new_count,
                         dup_count, 0, store_after, status))
            except Exception as e:  # לוג כושל לא חוסם
                logger.warning("manual_import_log insert failed: %s", e)

        summary.update({
            "neon_saved": True,
            "neon_verified_rows": present,
            "neon_verified_ok": verified_ok,
            "batch_id": batch_id,
            "neon_store_after": store_after,
        })
        logger.info("Neon save %s/%s mode=%s: %d records, %d present, store_after=%d",
                    project_id, kind, mode, len(records), present, store_after)
    except Exception as e:
        logger.exception("Neon save_entries failed: %s", e)
        summary["error"] = str(e)
    return summary


# ── טעינה + אימות ──────────────────────────────────────────────
def load_entries(project_id: str, kind: str) -> pd.DataFrame:
    """טוען את כל ההזנות של פרויקט+סוג מ-Neon לפורמט מאגר (כמו load_store).

    מחזיר DataFrame ריק (empty_frame) אם אין Neon / אין נתונים / שגיאה.
    """
    if not is_configured():
        return manual_store.empty_frame(kind)
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT raw_payload, row_hash, key_hash, month, "
                    "import_date, source_file FROM manual_entries "
                    "WHERE project_id=%s AND kind=%s",
                    (project_id, kind))
                rows = cur.fetchall()
    except Exception as e:
        logger.exception("Neon load_entries failed for %s/%s: %s",
                         project_id, kind, e)
        return manual_store.empty_frame(kind)

    if not rows:
        return manual_store.empty_frame(kind)

    recs: list[dict] = []
    for payload, row_hash, key_hash, month, import_date, source_file in rows:
        d = dict(payload or {})
        d["row_hash"] = row_hash
        d["key_hash"] = key_hash
        d["month"] = month
        d["import_date"] = import_date
        d["source_file"] = source_file
        recs.append(d)
    df = pd.DataFrame(recs)
    df = manual_store._coerce_types(kind, df)
    return df


def verify(project_id: str, kind: str, months: list[str] | None) -> dict:
    """אימות נוכחות הזנות ב-Neon לחודשים שנשמרו (קריאה חוזרת מהמקור).

    מחזיר את אותו מבנה כמו pipeline.verify_manual_in_master:
    {"rows_in_master": int, "months_found": [...], "ok": bool, "backend": "neon"}.
    """
    res = {"rows_in_master": 0, "months_found": [], "ok": False,
           "backend": "neon"}
    if not is_configured():
        return res
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT month, count(*) FROM manual_entries "
                    "WHERE project_id=%s AND kind=%s GROUP BY month",
                    (project_id, kind))
                rows = cur.fetchall()
    except Exception as e:
        logger.exception("Neon verify failed for %s/%s: %s", project_id, kind, e)
        return res

    found = sorted(m for m, _ in rows if m)
    total = int(sum(c for _, c in rows))
    res["rows_in_master"] = total
    res["months_found"] = found
    res["ok"] = bool(months) and all(m in found for m in (months or []))
    return res


def read_import_log(project_id: str | None = None) -> pd.DataFrame:
    """קורא את לוג היבוא מ-Neon (אופציונלית מסונן לפרויקט). ריק אם אין."""
    if not is_configured():
        return pd.DataFrame()
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            sql = ("SELECT ts, project_name, kind, month, mode, rows_saved, "
                   "new_count, duplicate_count, store_after, status, batch_id "
                   "FROM manual_import_log")
            params: tuple = ()
            if project_id:
                sql += " WHERE project_id=%s"
                params = (project_id,)
            sql += " ORDER BY ts DESC"
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                df = pd.DataFrame(cur.fetchall(), columns=cols)
        return df
    except Exception as e:
        logger.warning("Neon read_import_log failed: %s", e)
        return pd.DataFrame()


def delete_project_kind(project_id: str, kind: str) -> int:
    """מוחק את כל ההזנות של פרויקט+סוג מ-Neon. מחזיר מספר שורות שנמחקו."""
    if not is_configured():
        return 0
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM manual_entries WHERE project_id=%s AND kind=%s",
                        (project_id, kind))
                    return cur.rowcount
    except Exception as e:
        logger.exception("Neon delete_project_kind failed: %s", e)
        return 0


# ── רישום פרויקטים (registry) — התמדה קבועה בענן ────────────────
# בענן ``projects_registry.xlsx`` נכתב למערכת-קבצים זמנית ונמחק ב-reboot.
# לכן עריכת פרטי פרויקט (שם לקוח/סטטוס) חייבת להישמר כאן, ב-Neon.
# מחיקה מסומנת כ-tombstone (deleted_at) ולא נמחקת פיזית — כך פרויקט שנמחק
# בענן לא "צף מחדש" מתוך ה-xLSX המחויב.
_PROJECT_COLS = ["project_id", "project_name", "site_name", "client_name",
                 "status", "start_date", "end_date", "notes"]
_PROJECT_VALUE_COLS = ["project_name", "site_name", "client_name", "status",
                       "start_date", "end_date", "notes"]


def _txt(v):
    """ערך טקסט נקי ל-DB (None עבור NaN/ריק)."""
    try:
        if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


def _ensure_projects_schema(conn) -> None:
    """יוצר את טבלת projects_registry אם אינה קיימת (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projects_registry (
                project_id   TEXT PRIMARY KEY,
                project_name TEXT,
                site_name    TEXT,
                client_name  TEXT,
                status       TEXT,
                start_date   TEXT,
                end_date     TEXT,
                notes        TEXT,
                updated_at   TIMESTAMPTZ DEFAULT now(),
                deleted_at   TIMESTAMPTZ
            )
            """
        )


def save_project(row: dict) -> dict:
    """שומר/מעדכן שורת פרויקט ב-Neon (upsert) ומאמת ברמת-שדה.

    Returns:
        dict: {ok, verified, error?}. ``verified`` רק אם הקריאה החוזרת
        מהענן מחזירה בדיוק את הערכים שנכתבו (אימות אמיתי).
    """
    res = {"ok": False, "verified": False}
    if not is_configured():
        return res
    pid = (str(row.get("project_id")) or "").strip()
    if not pid:
        return res
    vals = {c: _txt(row.get(c)) for c in _PROJECT_VALUE_COLS}
    try:
        with _connect() as conn:
            _ensure_projects_schema(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO projects_registry
                          (project_id, project_name, site_name, client_name,
                           status, start_date, end_date, notes,
                           updated_at, deleted_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now(), NULL)
                        ON CONFLICT (project_id) DO UPDATE SET
                          project_name = EXCLUDED.project_name,
                          site_name    = EXCLUDED.site_name,
                          client_name  = EXCLUDED.client_name,
                          status       = EXCLUDED.status,
                          start_date   = EXCLUDED.start_date,
                          end_date     = EXCLUDED.end_date,
                          notes        = EXCLUDED.notes,
                          updated_at   = now(),
                          deleted_at   = NULL
                        """,
                        (pid, vals["project_name"], vals["site_name"],
                         vals["client_name"], vals["status"], vals["start_date"],
                         vals["end_date"], vals["notes"]))
            # read-back ברמת-שדה
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT project_name, site_name, client_name, status, "
                    "start_date, end_date, notes FROM projects_registry "
                    "WHERE project_id=%s AND deleted_at IS NULL", (pid,))
                got = cur.fetchone()
        verified = got is not None and all(
            (got[i] or "") == (vals[c] or "")
            for i, c in enumerate(_PROJECT_VALUE_COLS))
        res["ok"] = True
        res["verified"] = verified
        logger.info("Neon save_project %s verified=%s", pid, verified)
    except Exception as e:
        logger.exception("Neon save_project failed: %s", e)
        res["error"] = str(e)
    return res


def delete_project_row(project_id: str) -> bool:
    """מסמן פרויקט כמחוק ב-Neon (tombstone). מחזיר True אם הצליח."""
    if not is_configured():
        return False
    pid = (project_id or "").strip()
    if not pid:
        return False
    try:
        with _connect() as conn:
            _ensure_projects_schema(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO projects_registry
                          (project_id, deleted_at, updated_at)
                        VALUES (%s, now(), now())
                        ON CONFLICT (project_id) DO UPDATE SET
                          deleted_at = now(), updated_at = now()
                        """, (pid,))
        logger.info("Neon delete_project_row (tombstone) %s", pid)
        return True
    except Exception as e:
        logger.exception("Neon delete_project_row failed: %s", e)
        return False


def project_exists(project_id: str) -> bool:
    """האם הפרויקט קיים ופעיל (לא מחוק) ב-Neon."""
    if not is_configured():
        return False
    pid = (project_id or "").strip()
    if not pid:
        return False
    try:
        with _connect() as conn:
            _ensure_projects_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM projects_registry "
                    "WHERE project_id=%s AND deleted_at IS NULL", (pid,))
                return cur.fetchone() is not None
    except Exception as e:
        logger.warning("Neon project_exists failed: %s", e)
        return False


def fetch_projects_overlay() -> tuple[pd.DataFrame, set[str]]:
    """מחזיר (פרויקטים פעילים ב-Neon, קבוצת מזהי-פרויקט מחוקים) בחיבור אחד.

    משמש את project_store למיזוג: Neon מנצח על קונפליקטים, פרויקטים מחוקים
    מסוננים החוצה גם אם עדיין קיימים ב-xlsx המחויב.
    """
    active = pd.DataFrame(columns=_PROJECT_COLS)
    deleted: set[str] = set()
    if not is_configured():
        return active, deleted
    with _connect() as conn:  # שגיאות נזרקות לקורא — שיפול ל-xlsx
        _ensure_projects_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT project_id, project_name, site_name, client_name, "
                "status, start_date, end_date, notes FROM projects_registry "
                "WHERE deleted_at IS NULL")
            rows = cur.fetchall()
            cur.execute(
                "SELECT project_id FROM projects_registry "
                "WHERE deleted_at IS NOT NULL")
            deleted = {r[0] for r in cur.fetchall()}
    if rows:
        active = pd.DataFrame(rows, columns=_PROJECT_COLS)
    return active, deleted


def load_projects() -> pd.DataFrame:
    """מחזיר את כל הפרויקטים הפעילים מ-Neon (ללא tombstones)."""
    active, _ = fetch_projects_overlay()
    return active


def sync_projects_from_df(df: pd.DataFrame) -> dict:
    """דוחף את כל שורות ה-DataFrame ל-Neon (upsert). לסנכרון xlsx → ענן.

    Returns:
        dict: {total, verified, failed:[project_id,...]}.
    """
    out = {"total": 0, "verified": 0, "failed": []}
    if df is None or df.empty or not is_configured():
        return out
    for _, r in df.iterrows():
        out["total"] += 1
        res = save_project(r.to_dict())
        if res.get("verified"):
            out["verified"] += 1
        else:
            out["failed"].append(str(r.get("project_id")))
    return out
