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

# תתי-תיקיות ברירת מחדל לכל פרויקט חדש
DEFAULT_SUB_FOLDERS = ["documents", "uploads", "exports"]

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


def load_projects_registry() -> pd.DataFrame:
    """טוען את projects_registry.xlsx. מנרמל סטטוס + ממלא עמודות חסרות."""
    if not PROJECTS_REGISTRY.exists():
        logger.warning("projects_registry.xlsx not found at %s", PROJECTS_REGISTRY)
        return pd.DataFrame(columns=REGISTRY_COLS)
    try:
        df = pd.read_excel(PROJECTS_REGISTRY, engine="openpyxl")
        for c in REGISTRY_COLS:
            if c not in df.columns:
                df[c] = ""
        # נרמול סטטוס (closed→completed, on_hold→paused, וכו')
        df["status"] = df["status"].astype(str).apply(validate_project_status)
        return df[REGISTRY_COLS]
    except Exception as e:
        logger.exception("Failed to load projects_registry: %s", e)
        return pd.DataFrame(columns=REGISTRY_COLS)


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

    # Load registry + uniqueness check
    registry = load_projects_registry()
    if not registry.empty and pid in registry["project_id"].astype(str).values:
        return False, f"project_id '{pid}' כבר קיים - לא ניתן לדרוס", ""

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

    logger.info("Created project: %s (%s)", pid, pname)
    try:
        from core import db
        db.log_event("project_created", {
            "project_id": pid, "project_name": pname,
            "client": new_row.get("client_name", ""),
            "status": status,
        })
    except Exception:
        pass
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

    logger.info("Updated project %s: %s", pid, list(normalized.keys()))
    # audit
    try:
        from core import db
        db.log_event("project_updated", {
            "project_id": pid,
            "fields_changed": list(normalized.keys()),
        })
    except Exception:
        pass
    return True, "הפרויקט עודכן בהצלחה"


# ── Alias לתאימות לאחור ─────────────────────────────────────
def update_project_meta(project_id: str, updates: dict) -> tuple[bool, str]:
    """Alias ישן ל-update_project (תאימות לקוד קיים)."""
    return update_project(project_id, updates)


# ── Delete project ──────────────────────────────────────────
TRASH_DIR = DATA_ROOT / ".trash"


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
