"""שירות יצירה וניהול פרויקטים.

API:
    load_projects_registry()       - DataFrame מ-data/projects_registry.xlsx
    make_safe_project_id(name, existing) - מציע project_id באנגלית, ייחודי
    validate_project_id(pid)       - בודק שהמזהה חוקי (לא תופס, אנגלית, וכו')
    ensure_project_folders(pid)    - יוצר תיקיות בסיס לפרויקט
    create_project(project_data)   - upsert לרגיסטרי + יוצר תיקיות + project_meta.json

עקרון: לא דורסים פרויקט קיים. אם project_id כבר תפוס - שגיאה.
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

# סטטוסים אפשריים
VALID_STATUSES = ["active", "paused", "closed"]


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
def load_projects_registry() -> pd.DataFrame:
    """טוען את projects_registry.xlsx. מחזיר DataFrame עם הסכמה הסטנדרטית."""
    cols = ["project_id", "project_name", "site_name", "client_name",
            "status", "start_date", "notes"]
    if not PROJECTS_REGISTRY.exists():
        logger.warning("projects_registry.xlsx not found at %s", PROJECTS_REGISTRY)
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_excel(PROJECTS_REGISTRY, engine="openpyxl")
        # ודא שכל העמודות קיימות
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]
    except Exception as e:
        logger.exception("Failed to load projects_registry: %s", e)
        return pd.DataFrame(columns=cols)


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


def _write_project_meta(project_id: str, data: dict) -> Path:
    """כותב project_meta.json בתיקיית הפרויקט."""
    pdir = ensure_project_folders(project_id)
    meta_path = pdir / "project_meta.json"
    meta = dict(data)
    meta.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    # פורמט תאריכים לפי ISO
    if isinstance(meta.get("start_date"), (datetime, pd.Timestamp)):
        meta["start_date"] = pd.to_datetime(meta["start_date"]).strftime("%Y-%m-%d")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta_path


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
    status = project_data.get("status", "active")
    if status not in VALID_STATUSES:
        status = "active"

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
        "start_date": project_data.get("start_date") or "",
        "notes": (project_data.get("notes") or "").strip(),
    }

    # Format start_date
    sd = new_row["start_date"]
    if isinstance(sd, (datetime, pd.Timestamp)):
        new_row["start_date"] = pd.to_datetime(sd).strftime("%Y-%m-%d")

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
    return True, f"פרויקט '{pname}' נוצר בהצלחה", pid


def update_project_meta(project_id: str, updates: dict) -> tuple[bool, str]:
    """עדכון פרטי פרויקט קיים (לעתיד - כפתור 'ערוך פרטי פרויקט')."""
    registry = load_projects_registry()
    if registry.empty or project_id not in registry["project_id"].astype(str).values:
        return False, f"פרויקט '{project_id}' לא קיים"
    mask = registry["project_id"].astype(str) == project_id
    allowed = {"project_name", "site_name", "client_name", "status",
                "start_date", "notes"}
    for k, v in updates.items():
        if k in allowed:
            registry.loc[mask, k] = v
    try:
        _save_projects_registry(registry)
        # עדכן גם את project_meta.json
        existing_row = registry[mask].iloc[0].to_dict()
        _write_project_meta(project_id, existing_row)
        return True, "עודכן"
    except Exception as e:
        return False, f"שגיאה: {e}"
