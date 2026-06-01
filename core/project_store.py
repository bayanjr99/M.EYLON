"""שירות יצירה וניהול פרויקטים.

API:
    load_projects_registry()       - DataFrame מ-data/projects_registry.xlsx
    make_safe_project_id(name, existing) - מציע project_id באנגלית, ייחודי
    validate_project_id(pid)       - בודק שהמזהה חוקי
    validate_project_status(s)     - מאמת ערך סטטוס
    ensure_project_folders(pid)    - יוצר תיקיות בסיס לפרויקט
    create_project(project_data)   - upsert לרגיסטרי + יוצר תיקיות + project_meta.json
    update_project(pid, updated)   - מעדכן פרטי פרויקט (לא project_id)
    get_project_by_id(pid)         - dict עם פרטי הפרויקט (registry+meta)
    load_project_meta(pid)         - dict מתוך project_meta.json
    save_project_meta(pid, data)   - כותב project_meta.json

עקרון: לא דורסים פרויקט קיים בלי כוונה. project_id קבוע לאחר יצירה.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ── נתיבים ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
PROJECTS_REGISTRY = DATA_ROOT / "projects_registry.xlsx"
PROJECTS_DIR = DATA_ROOT / "projects"

# תתי-תיקיות ברירת מחדל לכל פרויקט חדש.
# imports/manual/reports/backups — מבנה עבודה מסודר לכל פרויקט;
# documents/uploads/exports — נשמרים לתאימות לאחור.
DEFAULT_SUB_FOLDERS = [
    "imports", "manual", "reports", "backups",
    "documents", "uploads", "exports",
]

# סטטוסים אפשריים + תרגום לעברית + צבע לתצוגה
VALID_STATUSES = ["active", "completed", "future", "paused", "archived"]

# Legacy aliases — סטטוסים ישנים ממופים לחדשים בטעינה
STATUS_ALIASES = {
    "closed": "completed",
    "on_hold": "paused",
    "": "active",
}

STATUS_HE = {
    "active":    "פעיל",
    "completed": "הסתיים",
    "future":    "עתידי",
    "paused":    "מושהה",
    "archived":  "ארכיון",
}

STATUS_COLOR = {
    "active":    "green",
    "completed": "gray",
    "future":    "blue",
    "paused":    "orange",
    "archived":  "dark",
}


def validate_project_status(status: str) -> str:
    """מחזיר סטטוס תקין. ערך לא מוכר → 'active'."""
    s = (status or "").strip().lower()
    s = STATUS_ALIASES.get(s, s)
    return s if s in VALID_STATUSES else "active"


# ── טרנסליטרציה עברית → אנגלית ────────────────────────────────
# מיפוי פונטי בסיסי. לא מושלם אבל פרקטי לשמות תיקיות.
# הערה: עברית בעיקר ללא ניקוד; מיפוי מנסה לתת חוויית "vowel-friendly".
HEBREW_TO_LATIN: dict[str, str] = {
    "א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h",
    "ו": "u", "ז": "z", "ח": "h", "ט": "t",
    "י": "i", "כ": "k", "ך": "k", "ל": "l",
    "מ": "m", "ם": "m", "נ": "n", "ן": "n",
    "ס": "s", "ע": "", "פ": "p", "ף": "f",
    "צ": "tz", "ץ": "tz", "ק": "k", "ר": "r",
    "ש": "sh", "ת": "t",
}

# מילים שמומלץ להוסיף אחריהן vowel מוסיף (לדוגמה: רישיון לציון → rishon)
# כרגע אנחנו לא עושים heuristics מתקדמים — המשתמש יכול לערוך

# מילים נפוצות בעברית שמוזיתות מה-id (חסרות משמעות לזיהוי הפרויקט)
COMMON_WORDS_TO_SKIP: set[str] = {
    "פרויקט", "פרוייקט", "אתר", "הפרויקט", "של", "את",
}

# regex לתווים חוקיים ב-project_id (אחרי טרנסליטרציה)
_VALID_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,50}$")


def _strip_niqqud(text: str) -> str:
    """מסיר ניקוד מטקסט עברי."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _romanize_word(word: str) -> str:
    """ממיר מילה עברית לאנגלית פונטית."""
    out = []
    for c in word:
        if c in HEBREW_TO_LATIN:
            out.append(HEBREW_TO_LATIN[c])
        elif c.isascii():
            out.append(c.lower())
        # שאר התווים (סינים/ערבית/וכו') - דילוג
    result = "".join(out)
    # נקה תווים לא חוקיים
    result = re.sub(r"[^a-z0-9_]", "", result.lower())
    return result


def make_safe_project_id(name: str, existing: set[str] | None = None) -> str:
    """ממציע project_id באנגלית בטוח לשימוש בתיקיות, ייחודי.

    דוגמה:
        "פרויקט אום אל פחם"  →  "um_al_fahm"
        "ראשון לציון"        →  "rishon_ltzion"
        אם כבר קיים           →  מוסיף סיומת _2, _3, ...
    """
    if not name:
        return ""
    name = _strip_niqqud(name).strip()
    words = name.split()
    # סנן מילים נפוצות
    filtered = [w for w in words if w not in COMMON_WORDS_TO_SKIP]
    if not filtered:
        filtered = words  # אם הכל סונן - השאר את הכל

    parts = [_romanize_word(w) for w in filtered]
    parts = [p for p in parts if p]  # סנן ריקים
    if not parts:
        parts = ["project"]
    base = "_".join(parts)

    # מוודא שמתחיל באות (לא ספרה/_)
    if not base or not base[0].isalpha():
        base = "p_" + base

    # קיצור אם ארוך מדי
    base = base[:48]

    if not existing:
        return base
    if base not in existing:
        return base
    # חפש סיומת ייחודית
    n = 2
    while f"{base}_{n}" in existing and n < 1000:
        n += 1
    return f"{base}_{n}"


def validate_project_id(project_id: str) -> tuple[bool, str]:
    """בודק שה-project_id חוקי. מחזיר (is_valid, error_message)."""
    if not project_id or not project_id.strip():
        return False, "project_id חובה"
    pid = project_id.strip()
    if not _VALID_PROJECT_ID_RE.match(pid):
        return False, ("project_id חייב להיות: באנגלית בלבד, lowercase, "
                       "ללא רווחים, להתחיל באות, אורך 2-50 תווים, "
                       "מותר רק [a-z 0-9 _]")
    return True, ""


# ── Registry I/O ──────────────────────────────────────────────
REGISTRY_COLS = ["project_id", "project_name", "site_name", "client_name",
                 "status", "start_date", "end_date", "notes"]


# ── Neon source-of-truth helpers (Part 7) ────────────────────
def _neon_on() -> bool:
    """האם Neon מוגדר (מקור האמת לפרויקטים). זול — לא פותח חיבור."""
    try:
        from core import cloud_db
        return cloud_db.is_configured()
    except Exception:
        return False


def _registry_signature(df: pd.DataFrame) -> list[dict]:
    """חתימה מנורמלת של רגיסטרי להשוואה (כל הערכים כמחרוזת)."""
    if df is None or df.empty:
        return []
    d = df.reindex(columns=REGISTRY_COLS).fillna("").astype(str)
    return d.to_dict("records")


def _load_local_registry() -> pd.DataFrame:
    """טוען את projects_registry.xlsx המקומי. מנרמל סטטוס + עמודות חסרות."""
    if not PROJECTS_REGISTRY.exists():
        return pd.DataFrame(columns=REGISTRY_COLS)
    try:
        df = pd.read_excel(PROJECTS_REGISTRY, engine="openpyxl")
        for c in REGISTRY_COLS:
            if c not in df.columns:
                df[c] = ""
        df["status"] = df["status"].astype(str).apply(validate_project_status)
        return df[REGISTRY_COLS]
    except Exception as e:
        logger.exception("Failed to load local projects_registry: %s", e)
        return pd.DataFrame(columns=REGISTRY_COLS)


def _mirror_registry_to_local(df: pd.DataFrame) -> None:
    """כותב את רשימת הפרויקטים מ-Neon לקובץ המקומי — רק אם השתנה.

    כתיבה רק על שינוי תוכן מונעת bumping מיותר של mtime (שמבטל את
    קאש ה-Streamlit ויוצר רענונים מיותרים). best-effort — לא חוסם.
    """
    try:
        if _registry_signature(_load_local_registry()) == _registry_signature(df):
            return
        _save_projects_registry(df.reindex(columns=REGISTRY_COLS))
    except Exception as e:
        logger.warning("Mirror registry to local failed (non-fatal): %s", e)


def _seed_neon_from_local(local: pd.DataFrame) -> None:
    """מהגר רגיסטרי מקומי קיים ל-Neon פעם אחת (כש-Neon ריק)."""
    try:
        from core import cloud_db
        for _, r in local.iterrows():
            row = {c: r.get(c, "") for c in REGISTRY_COLS}
            cloud_db.save_project(row)
        logger.info("Seeded %d local projects into Neon", len(local))
    except Exception as e:
        logger.warning("Seeding Neon from local failed (non-fatal): %s", e)


def load_projects_registry() -> pd.DataFrame:
    """טוען את רשימת הפרויקטים. כש-Neon מוגדר — Neon הוא מקור האמת.

    סדר: (1) אם Neon לא מוגדר → קובץ מקומי בלבד (התנהגות מקורית).
    (2) אם Neon מוגדר ויש בו פרויקטים → מחזיר אותם + מסנכרן לקובץ המקומי
    (mirror). (3) אם Neon מוגדר וריק אך יש רגיסטרי מקומי → מהגר אותו
    ל-Neon פעם אחת ואז מחזיר מ-Neon. כך פרויקטים שורדים reboot.
    """
    if not _neon_on():
        return _load_local_registry()

    try:
        from core import cloud_db
        ndf = cloud_db.load_projects()
    except Exception as e:
        logger.warning("Neon load_projects failed, using local: %s", e)
        return _load_local_registry()

    if ndf is None or ndf.empty:
        local = _load_local_registry()
        if local.empty:
            return local
        _seed_neon_from_local(local)
        try:
            ndf = cloud_db.load_projects()
        except Exception:
            ndf = None
        if ndf is None or ndf.empty:
            return local  # שמירה על המקומי אם המיגרציה נכשלה

    for c in REGISTRY_COLS:
        if c not in ndf.columns:
            ndf[c] = ""
    ndf["status"] = ndf["status"].astype(str).apply(validate_project_status)
    ndf = ndf[REGISTRY_COLS]
    _mirror_registry_to_local(ndf)
    return ndf


def _mirror_project_local(row: dict) -> None:
    """mirror מקומי לפרויקט בודד (תיקיות + meta + registry) — best-effort."""
    pid = str(row.get("project_id") or "").strip()
    if not pid:
        return
    try:
        ensure_project_folders(pid)
        _write_project_meta(pid, row)
    except Exception as e:
        logger.warning("Local folders/meta mirror failed for %s: %s", pid, e)
    try:
        reg = _load_local_registry()
        reg = reg[reg["project_id"].astype(str) != pid]
        reg = pd.concat([reg, pd.DataFrame([{c: row.get(c, "") for c in REGISTRY_COLS}])],
                        ignore_index=True)
        _save_projects_registry(reg[REGISTRY_COLS])
    except Exception as e:
        logger.warning("Local registry mirror failed for %s: %s", pid, e)


def _audit_project_event(event: str, payload: dict) -> None:
    """רישום אירוע פרויקט ללוג הביקורת (SQLite) — best-effort, לא חוסם."""
    try:
        from core import db
        db.log_event(event, payload)
    except Exception:
        pass


def _save_projects_registry(df: pd.DataFrame) -> None:
    """כותב את הרגיסטרי חזרה לאקסל."""
    PROJECTS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(PROJECTS_REGISTRY, index=False, engine="openpyxl")
    logger.info("Wrote %d projects to %s", len(df), PROJECTS_REGISTRY)


# ── Folder management ─────────────────────────────────────────
def ensure_project_folders(project_id: str) -> Path:
    """יוצר את כל תיקיות הבסיס לפרויקט. מחזיר את תיקיית הפרויקט."""
    pdir = PROJECTS_DIR / project_id
    pdir.mkdir(parents=True, exist_ok=True)
    for sub in DEFAULT_SUB_FOLDERS:
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    logger.info("Ensured folders for project: %s", pdir)
    return pdir


def _meta_path(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "project_meta.json"


def _fmt_date(v) -> str:
    """ISO date string או '' אם ריק."""
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.to_datetime(v).strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(v).strftime("%Y-%m-%d")
    except Exception:
        return str(v)


def _write_project_meta(project_id: str, data: dict) -> Path:
    """כותב project_meta.json בתיקיית הפרויקט (משמר created_at קיים)."""
    pdir = ensure_project_folders(project_id)
    meta_path = pdir / "project_meta.json"

    # שמירה על created_at שכבר קיים בקובץ הישן
    existing = {}
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as f:
                existing = json.load(f) or {}
        except Exception:
            existing = {}

    meta = dict(data)
    meta["created_at"] = existing.get("created_at") or datetime.now().isoformat(timespec="seconds")
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta["start_date"] = _fmt_date(meta.get("start_date"))
    meta["end_date"] = _fmt_date(meta.get("end_date"))

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta_path


def save_project_meta(project_id: str, data: dict) -> Path:
    """API ציבורי לכתיבת project_meta.json."""
    return _write_project_meta(project_id, data)


def _field_matches(field: str, expected, actual) -> bool:
    """השוואה סלחנית בין ערך מבוקש לערך שנקרא חזרה מהדיסק.

    תאריכים מושווים אחרי נרמול ל-ISO; סטטוס אחרי נרמול; שאר השדות
    כמחרוזת מנוקה. מטפל ב-NaN/NaT.
    """
    if field in ("start_date", "end_date"):
        return _fmt_date(expected) == _fmt_date(actual)
    if field == "status":
        return validate_project_status(expected) == validate_project_status(actual)
    try:
        if actual is None or (not isinstance(actual, str) and pd.isna(actual)):
            actual = ""
    except (TypeError, ValueError):
        pass
    return str(expected or "").strip() == str(actual or "").strip()


def verify_project_persisted(project_id: str, expected: dict | None = None) -> dict:
    """קורא מחדש מהדיסק ומוודא שהפרויקט נשמר באמת (read-back).

    בודק: (1) הפרויקט קיים ברגיסטרי; (2) תיקיית הפרויקט קיימת;
    (3) project_meta.json קיים; (4) אם expected סופק — שהשדות תואמים.

    Returns:
        dict: {ok, in_registry, folder_exists, meta_exists, mismatches:[...]}.
    """
    result = {"ok": False, "in_registry": False, "folder_exists": False,
              "meta_exists": False, "mismatches": []}
    pid = (project_id or "").strip()
    if not pid:
        return result

    # כש-Neon מקור האמת: האימות הקובע הוא מול Neon (read-back מהמקור).
    # קבצים מקומיים (folder/meta) הם mirror בלבד — לא נדרשים ל-ok, כי
    # על Streamlit Cloud הם עלולים להיעלם ב-restart.
    if _neon_on():
        try:
            from core import cloud_db
            nres = cloud_db.verify_project(pid, expected)
            result["in_registry"] = nres.get("in_neon", False)
            result["in_neon"] = nres.get("in_neon", False)
            result["folder_exists"] = (PROJECTS_DIR / pid).exists()
            result["meta_exists"] = _meta_path(pid).exists()
            result["mismatches"] = nres.get("mismatches", [])
            result["ok"] = nres.get("ok", False)
            result["backend"] = "neon"
            return result
        except Exception as e:
            logger.warning("Neon verify_project failed, using local: %s", e)

    registry = load_projects_registry()
    rows = registry[registry["project_id"].astype(str) == pid] \
        if not registry.empty else registry
    result["in_registry"] = bool(len(rows))
    result["folder_exists"] = (PROJECTS_DIR / pid).exists()
    result["meta_exists"] = _meta_path(pid).exists()

    if result["in_registry"] and expected:
        saved = rows.iloc[0].to_dict()
        for k, v in expected.items():
            if k in REGISTRY_COLS and not _field_matches(k, v, saved.get(k)):
                result["mismatches"].append(k)

    result["ok"] = (result["in_registry"] and result["folder_exists"]
                    and result["meta_exists"] and not result["mismatches"])
    return result


def load_project_meta(project_id: str) -> dict:
    """טוען project_meta.json. מחזיר dict ריק אם לא קיים."""
    p = _meta_path(project_id)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        logger.warning("Failed to load project_meta for %s: %s", project_id, e)
        return {}


def get_project_by_id(project_id: str) -> dict | None:
    """מחזיר dict עם פרטי הפרויקט (registry + meta). None אם לא קיים."""
    registry = load_projects_registry()
    if registry.empty:
        return None
    rows = registry[registry["project_id"].astype(str) == project_id]
    if rows.empty:
        return None
    row = rows.iloc[0].to_dict()
    # ממזג meta.json אם יש שדות נוספים שלא ברגיסטרי
    meta = load_project_meta(project_id)
    for k, v in meta.items():
        if k not in row or not row.get(k):
            row[k] = v
    return row


# ── Create project ────────────────────────────────────────────
def create_project(project_data: dict) -> tuple[bool, str, str]:
    """יוצר פרויקט חדש: רישום ברגיסטרי + תיקיות + project_meta.json.

    Args:
        project_data: dict עם מפתחות project_id, project_name, site_name,
                      client_name, status, start_date, notes.

    Returns:
        (success, message, project_id_created)
    """
    pid = (project_data.get("project_id") or "").strip()
    pname = (project_data.get("project_name") or "").strip()

    if not pname:
        return False, "שם פרויקט חובה", ""
    if not pid:
        return False, "project_id חובה", ""

    # Validate id format
    ok, err = validate_project_id(pid)
    if not ok:
        return False, err, ""

    # Validate status
    status = validate_project_status(project_data.get("status", "active"))

    # Load registry + uniqueness check (גם לפי מזהה וגם לפי שם)
    registry = load_projects_registry()
    if not registry.empty and pid in registry["project_id"].astype(str).values:
        return False, f"project_id '{pid}' כבר קיים - לא ניתן לדרוס", ""
    if not registry.empty:
        from utils.hebrew import match_normalize
        existing_names = registry["project_name"].fillna("").astype(str).apply(match_normalize)
        if match_normalize(pname) in set(existing_names):
            return False, f"פרויקט בשם '{pname}' כבר קיים", ""

    # Build new row
    new_row = {
        "project_id": pid,
        "project_name": pname,
        "site_name": (project_data.get("site_name") or pname).strip(),
        "client_name": (project_data.get("client_name") or "").strip(),
        "status": status,
        "start_date": _fmt_date(project_data.get("start_date")),
        "end_date": _fmt_date(project_data.get("end_date")),
        "notes": (project_data.get("notes") or "").strip(),
    }

    # ── מסלול Neon (מקור אמת): כתיבה ל-Neon + read-back ──
    if _neon_on():
        from core import cloud_db
        sres = cloud_db.save_project(new_row)
        if not sres.get("neon_verified_ok"):
            err = sres.get("error") or (
                f"שדות לא תואמים ב-read-back: {sres.get('mismatches')}")
            logger.error("create_project Neon read-back failed for %s: %s", pid, sres)
            return False, (f"הפרויקט לא נשמר ב-Neon (לא אומת) — {err}"), ""
        # mirror מקומי (תיקיות נדרשות ליבוא קבצים) — best-effort, לא חוסם
        _mirror_project_local(new_row)
        logger.info("Created project in Neon (verified): %s (%s)", pid, pname)
        _audit_project_event("project_created", {
            "project_id": pid, "project_name": pname,
            "client": new_row.get("client_name", ""), "status": status,
            "backend": "neon"})
        return True, f"פרויקט '{pname}' נוצר ונשמר ב-Neon", pid

    # ── מסלול מקומי בלבד (Neon לא מוגדר) ──
    # Append + save xlsx
    new_df = pd.concat([registry, pd.DataFrame([new_row])], ignore_index=True)
    try:
        _save_projects_registry(new_df)
    except PermissionError:
        return False, ("לא ניתן לכתוב ל-projects_registry.xlsx. "
                       "סגור את הקובץ ב-Excel ונסה שוב."), ""
    except Exception as e:
        logger.exception("Failed to write registry: %s", e)
        return False, f"שגיאה בכתיבת הרגיסטרי: {e}", ""

    # Create folders + meta
    try:
        ensure_project_folders(pid)
        _write_project_meta(pid, new_row)
    except Exception as e:
        logger.exception("Failed to create project folders: %s", e)
        return False, f"הרגיסטרי עודכן אבל יצירת תיקיות נכשלה: {e}", pid

    # read-back: לא להחזיר הצלחה לפני קריאה חוזרת מהדיסק שמאמתת שהכל נשמר
    check = verify_project_persisted(pid, new_row)
    if not check["ok"]:
        logger.error("create_project read-back failed for %s: %s", pid, check)
        return False, ("הפרויקט נכתב אך האימות (read-back) נכשל — "
                       f"registry={check['in_registry']}, "
                       f"folder={check['folder_exists']}, "
                       f"meta={check['meta_exists']}, "
                       f"שדות לא תואמים={check['mismatches']}"), pid

    logger.info("Created project (verified): %s (%s)", pid, pname)
    _audit_project_event("project_created", {
        "project_id": pid, "project_name": pname,
        "client": new_row.get("client_name", ""), "status": status})
    return True, f"פרויקט '{pname}' נוצר בהצלחה", pid


def update_project(project_id: str, updated_data: dict) -> tuple[bool, str]:
    """עדכון פרטי פרויקט קיים.

    מעדכן את projects_registry.xlsx + project_meta.json.
    לא מוחק תיקיות, לא מוחק נתונים, לא משנה project_id.

    שדות מותרים: project_name, site_name, client_name, status,
                  start_date, end_date, notes.

    Returns:
        (success, message)
    """
    pid = (project_id or "").strip()
    if not pid:
        return False, "project_id חסר"

    registry = load_projects_registry()
    if registry.empty or pid not in registry["project_id"].astype(str).values:
        return False, f"פרויקט '{pid}' לא נמצא ברגיסטרי"

    pname = (updated_data.get("project_name") or "").strip()
    if "project_name" in updated_data and not pname:
        return False, "שם פרויקט חובה"

    # נרמול ערכים
    allowed = {"project_name", "site_name", "client_name", "status",
               "start_date", "end_date", "notes"}
    normalized: dict = {}
    for k, v in updated_data.items():
        if k not in allowed:
            continue
        if k == "status":
            normalized[k] = validate_project_status(v)
        elif k in ("start_date", "end_date"):
            normalized[k] = _fmt_date(v)
        elif isinstance(v, str):
            normalized[k] = v.strip()
        else:
            normalized[k] = v

    # ── מסלול Neon (מקור אמת): מיזוג על השורה הקיימת + UPSERT + read-back ──
    if _neon_on():
        from core import cloud_db
        existing = cloud_db.load_project(pid) or {}
        # בסיס מהרגיסטרי (כבר Neon-backed) אם load_project לא החזיר
        if not existing:
            base = registry[registry["project_id"].astype(str) == pid].iloc[0].to_dict()
            existing = {c: ("" if base.get(c) is None else str(base.get(c)))
                        for c in REGISTRY_COLS}
        merged = {c: existing.get(c, "") for c in REGISTRY_COLS}
        merged["project_id"] = pid
        merged.update(normalized)
        sres = cloud_db.save_project(merged)
        if not sres.get("neon_verified_ok"):
            err = sres.get("error") or (
                f"שדות לא תואמים ב-read-back: {sres.get('mismatches')}")
            logger.error("update_project Neon read-back failed for %s: %s", pid, sres)
            return False, f"העדכון לא נשמר ב-Neon (לא אומת) — {err}"
        _mirror_project_local(merged)
        logger.info("Updated project in Neon (verified) %s: %s",
                    pid, list(normalized.keys()))
        _audit_project_event("project_updated", {
            "project_id": pid, "fields_changed": list(normalized.keys()),
            "backend": "neon"})
        return True, "הפרויקט עודכן ונשמר ב-Neon"

    # ── מסלול מקומי בלבד (Neon לא מוגדר) ──
    # החלת השינויים על שורת הרגיסטרי.
    # pandas 2.x קפדני על dtypes: עמודה שנטענה כ-float64 (כי כל הערכים NaN)
    # תזרוק TypeError אם ננסה לכתוב מחרוזת. ננרמל הכל לאובייקט קודם.
    mask = registry["project_id"].astype(str) == pid
    for k in normalized.keys():
        if k in registry.columns:
            registry[k] = registry[k].astype(object)
    for k, v in normalized.items():
        registry.loc[mask, k] = v

    try:
        _save_projects_registry(registry)
    except PermissionError:
        return False, ("לא ניתן לכתוב ל-projects_registry.xlsx. "
                       "סגור את הקובץ ב-Excel ונסה שוב.")
    except Exception as e:
        logger.exception("Failed to write registry: %s", e)
        return False, f"שגיאה בכתיבת הרגיסטרי: {e}"

    # עדכון project_meta.json מהשורה החדשה
    try:
        row = registry[mask].iloc[0].to_dict()
        _write_project_meta(pid, row)
    except Exception as e:
        logger.exception("Failed to write project_meta.json: %s", e)
        return False, f"הרגיסטרי עודכן אבל כתיבת project_meta.json נכשלה: {e}"

    # read-back: לא להחזיר הצלחה לפני קריאה חוזרת מהדיסק שמאמתת את השינוי
    check = verify_project_persisted(pid, normalized)
    if not check["ok"]:
        logger.error("update_project read-back failed for %s: %s", pid, check)
        return False, ("העדכון נכתב אך האימות (read-back) נכשל — "
                       f"שדות שלא נשמרו: {check['mismatches'] or 'לא ידוע'}")

    logger.info("Updated project (verified) %s: %s", pid, list(normalized.keys()))
    _audit_project_event("project_updated", {
        "project_id": pid, "fields_changed": list(normalized.keys())})
    return True, "הפרויקט עודכן בהצלחה"


# ── Alias לתאימות לאחור ─────────────────────────────────────
def update_project_meta(project_id: str, updates: dict) -> tuple[bool, str]:
    """Alias ישן ל-update_project (תאימות לקוד קיים)."""
    return update_project(project_id, updates)


# ── Delete project ──────────────────────────────────────────
TRASH_DIR = DATA_ROOT / ".trash"


def _move_folder_to_trash(project_id: str) -> str | None:
    """מעביר את תיקיית הפרויקט לסל מיחזור (הפיך). best-effort — None בכשל."""
    import shutil
    pid = (project_id or "").strip()
    pdir = PROJECTS_DIR / pid
    if not pid or not pdir.exists():
        return None
    try:
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = TRASH_DIR / f"{pid}_{ts}"
        shutil.move(str(pdir), str(dest))
        logger.info("Moved project folder to trash: %s", dest)
        return str(dest)
    except Exception as e:
        logger.warning("Failed to move folder to trash for %s: %s", pid, e)
        return None


def delete_project(project_id: str,
                    delete_folder: bool = True) -> tuple[bool, str, str | None]:
    """מוחק פרויקט: מסיר מהרגיסטרי + מעביר תיקייה לסל מיחזור.

    **הפעולה הפיכה ידנית** — התיקייה לא נמחקת באמת אלא עוברת אל
    ``data/.trash/<project_id>_<timestamp>/``. ניתן לשחזר על-ידי
    החזרה ידנית של התיקייה אל ``data/projects/`` והוספה לרגיסטרי.

    Args:
        project_id: מזהה הפרויקט למחיקה.
        delete_folder: אם True (ברירת מחדל), התיקייה תועבר לסל מיחזור.
                       אם False, רק נמחק מהרגיסטרי (תיקייה נשארת).

    Returns:
        (success, message, trash_path_or_None)
    """
    import shutil

    pid = (project_id or "").strip()
    if not pid:
        return False, "project_id חסר", None

    registry = load_projects_registry()
    if registry.empty or pid not in registry["project_id"].astype(str).values:
        return False, f"פרויקט '{pid}' לא נמצא ברגיסטרי", None

    # ── מסלול Neon (מקור אמת): soft-delete + אימות שהפרויקט הוסר ──
    # soft-delete הפיך (is_deleted=TRUE) — לא מוחקים נתונים לצמיתות.
    if _neon_on():
        from core import cloud_db
        dres = cloud_db.delete_project(pid, hard=False)
        if not dres.get("neon_verified_ok"):
            err = dres.get("error") or "הפרויקט עדיין מופיע כפעיל ב-Neon"
            logger.error("delete_project Neon failed for %s: %s", pid, dres)
            return False, f"המחיקה לא אומתה מול Neon — {err}", None
        # mirror מקומי: הסרה מהרגיסטרי + העברת תיקייה לסל מיחזור (best-effort)
        try:
            new_registry = _load_local_registry()
            new_registry = new_registry[new_registry["project_id"].astype(str) != pid]
            _save_projects_registry(new_registry[REGISTRY_COLS])
        except Exception as e:
            logger.warning("Local registry mirror on delete failed: %s", e)
        trash_path = _move_folder_to_trash(pid) if delete_folder else None
        logger.info("Deleted project %s in Neon (soft) (trash=%s)", pid, trash_path)
        _audit_project_event("project_deleted", {
            "project_id": pid, "delete_folder": delete_folder,
            "trash_path": trash_path, "backend": "neon"})
        msg = f"הפרויקט '{pid}' נמחק (Neon)"
        if trash_path:
            msg += f". התיקייה הועברה ל-{trash_path}"
        return True, msg, trash_path

    # ── מסלול מקומי בלבד (Neon לא מוגדר) ──
    # שלב 1: הסרה מהרגיסטרי
    new_registry = registry[registry["project_id"].astype(str) != pid].copy()
    try:
        _save_projects_registry(new_registry)
    except PermissionError:
        return False, ("לא ניתן לכתוב ל-projects_registry.xlsx. "
                       "סגור את הקובץ ב-Excel ונסה שוב."), None
    except Exception as e:
        logger.exception("Failed to write registry on delete: %s", e)
        return False, f"שגיאה בכתיבת הרגיסטרי: {e}", None

    # שלב 2: העברת התיקייה לסל מיחזור (אופציונלי)
    trash_path: str | None = None
    if delete_folder:
        pdir = PROJECTS_DIR / pid
        if pdir.exists():
            try:
                TRASH_DIR.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = TRASH_DIR / f"{pid}_{ts}"
                shutil.move(str(pdir), str(dest))
                trash_path = str(dest)
                logger.info("Moved project folder to trash: %s", dest)
            except Exception as e:
                # אם ההעברה נכשלה — נחזיר הרגיסטרי למצב קודם
                logger.exception("Failed to move folder to trash: %s", e)
                try:
                    _save_projects_registry(registry)
                except Exception:
                    pass
                return False, (f"שגיאה בהעברת התיקייה לסל מיחזור: {e}. "
                               f"הרגיסטרי שוחזר."), None

    logger.info("Deleted project %s (folder=%s, trash=%s)",
                pid, delete_folder, trash_path)
    try:
        from core import db
        db.log_event("project_deleted", {
            "project_id": pid,
            "delete_folder": delete_folder,
            "trash_path": trash_path,
        })
    except Exception:
        pass
    msg = f"הפרויקט '{pid}' נמחק"
    if trash_path:
        msg += f". התיקייה הועברה ל-{trash_path}"
    return True, msg, trash_path
