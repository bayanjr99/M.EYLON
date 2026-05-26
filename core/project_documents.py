"""מסמכי פרויקט — SQLite layer + שמירה לדיסק.

קבצים נשמרים תחת:  data/projects/<project_id>/documents/<filename>
מטא-דאטה ב-SQLite (project_control.sqlite):

טבלה: project_documents
שדות:
    id           INTEGER PRIMARY KEY
    project_id   TEXT NOT NULL
    filename     TEXT NOT NULL
    filepath     TEXT NOT NULL  (יחסי לתיקיית הפרויקט)
    doc_type     TEXT (invoice / agreement / photo / pdf / excel / other)
    month        TEXT (MM-YYYY, אופציונלי)
    supplier     TEXT (אופציונלי)
    client       TEXT (אופציונלי)
    license_num  INTEGER (כלי, אופציונלי)
    notes        TEXT
    file_hash    TEXT (SHA-256 לזיהוי כפילויות)
    file_size    INTEGER (bytes)
    uploaded_at  TEXT
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "project_control.sqlite"
PROJECTS_DIR = Path(__file__).resolve().parent.parent / "data" / "projects"


DOC_TYPES = ("invoice", "agreement", "photo", "pdf", "excel", "other")
DOC_TYPE_HE = {
    "invoice":   "חשבונית",
    "agreement": "הסכם",
    "photo":     "תמונה",
    "pdf":       "PDF",
    "excel":     "אקסל",
    "other":     "אחר",
}

# סיומת → סוג מומלץ
EXT_TO_TYPE = {
    ".pdf":  "pdf",
    ".xls":  "excel", ".xlsx": "excel", ".csv": "excel",
    ".jpg":  "photo", ".jpeg": "photo", ".png": "photo", ".heic": "photo",
    ".doc":  "agreement", ".docx": "agreement",
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS project_documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,
    filename     TEXT NOT NULL,
    filepath     TEXT NOT NULL,
    doc_type     TEXT DEFAULT 'other',
    month        TEXT DEFAULT '',
    supplier     TEXT DEFAULT '',
    client       TEXT DEFAULT '',
    license_num  INTEGER DEFAULT NULL,
    notes        TEXT DEFAULT '',
    file_hash    TEXT DEFAULT '',
    file_size    INTEGER DEFAULT 0,
    uploaded_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_project   ON project_documents(project_id);
CREATE INDEX IF NOT EXISTS idx_docs_hash      ON project_documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_docs_supplier  ON project_documents(supplier);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def _docs_dir(project_id: str) -> Path:
    p = PROJECTS_DIR / project_id / "documents"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_doc_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return EXT_TO_TYPE.get(ext, "other")


def find_duplicate(project_id: str, file_hash: str) -> dict | None:
    """מחזיר רשומה קיימת אם hash זהה כבר במערכת."""
    init_db()
    with _conn() as c:
        cur = c.execute(
            "SELECT id, filename, doc_type, uploaded_at FROM project_documents "
            "WHERE project_id = ? AND file_hash = ? LIMIT 1",
            (project_id, file_hash),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "filename": row[1],
            "doc_type": row[2], "uploaded_at": row[3]}


def save_document(project_id: str, filename: str, data: bytes, *,
                    doc_type: str = "other",
                    month: str = "", supplier: str = "",
                    client: str = "", license_num: int | None = None,
                    notes: str = "",
                    allow_duplicate: bool = False) -> tuple[bool, str, int | None]:
    """שומר מסמך בדיסק + מטא-דאטה ב-SQLite.

    מחזיר (success, message, id) — אם duplicate, success=False
    אלא אם allow_duplicate=True (אז שומר עם שם חדש).
    """
    init_db()
    if doc_type not in DOC_TYPES:
        doc_type = "other"

    file_hash = _hash_bytes(data)
    file_size = len(data)

    # בדיקת כפילות
    dup = find_duplicate(project_id, file_hash)
    if dup and not allow_duplicate:
        return (False,
                f"קובץ זהה כבר קיים במערכת: '{dup['filename']}' "
                f"(הועלה {dup['uploaded_at']})",
                dup["id"])

    # שמירה לדיסק
    docs = _docs_dir(project_id)
    target = docs / filename
    # אם קובץ עם אותו שם קיים אבל hash שונה → הוסף סיומת
    if target.exists() and target.read_bytes() != data:
        stem, ext = Path(filename).stem, Path(filename).suffix
        i = 1
        while (docs / f"{stem}_{i}{ext}").exists():
            i += 1
        target = docs / f"{stem}_{i}{ext}"
        filename = target.name

    try:
        target.write_bytes(data)
    except Exception as e:
        logger.exception("Failed to write document: %s", e)
        return False, f"שגיאה בשמירה לדיסק: {e}", None

    # רישום ל-DB
    rel_path = str(target.relative_to(PROJECTS_DIR / project_id))
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO project_documents
               (project_id, filename, filepath, doc_type, month, supplier,
                client, license_num, notes, file_hash, file_size, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, filename, rel_path, doc_type, month.strip(),
             supplier.strip(), client.strip(), license_num,
             notes.strip(), file_hash, file_size, now),
        )
        new_id = int(cur.lastrowid)

    return True, f"נשמר: {filename}", new_id


def list_documents(project_id: str, *,
                    doc_type: str | None = None,
                    month: str | None = None,
                    supplier: str | None = None,
                    license_num: int | None = None) -> pd.DataFrame:
    """מחזיר DataFrame של מסמכי הפרויקט עם פילטרים אופציונליים."""
    init_db()
    q = "SELECT * FROM project_documents WHERE project_id = ?"
    params: list = [project_id]
    if doc_type and doc_type in DOC_TYPES:
        q += " AND doc_type = ?"
        params.append(doc_type)
    if month:
        q += " AND month = ?"
        params.append(month)
    if supplier:
        q += " AND supplier = ?"
        params.append(supplier)
    if license_num is not None:
        q += " AND license_num = ?"
        params.append(license_num)
    q += " ORDER BY uploaded_at DESC, id DESC"
    with _conn() as c:
        return pd.read_sql_query(q, c, params=params)


def get_document_bytes(doc_id: int) -> tuple[bytes, str] | None:
    """מחזיר (bytes, filename) של מסמך לפי id, או None אם לא קיים."""
    init_db()
    with _conn() as c:
        cur = c.execute(
            "SELECT project_id, filename, filepath FROM project_documents "
            "WHERE id = ?", (doc_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    project_id, filename, rel_path = row
    p = PROJECTS_DIR / project_id / rel_path
    if not p.exists():
        return None
    return p.read_bytes(), filename


def delete_document(doc_id: int, delete_file: bool = True) -> bool:
    """מסיר רשומה מ-DB + אופציונלית מוחק קובץ."""
    init_db()
    with _conn() as c:
        cur = c.execute(
            "SELECT project_id, filepath FROM project_documents WHERE id = ?",
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        project_id, rel_path = row
        c.execute("DELETE FROM project_documents WHERE id = ?", (doc_id,))

    if delete_file:
        p = PROJECTS_DIR / project_id / rel_path
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            logger.warning("Could not delete file %s: %s", p, e)

    return True


def count_documents(project_id: str) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "SELECT COUNT(*) FROM project_documents WHERE project_id = ?",
            (project_id,),
        )
        return int(cur.fetchone()[0])
