"""מיגרציה חד-פעמית: העלאת ההזנות הידניות המקומיות (parquet) ל-Neon.

מעלה את כל מאגרי הסולר/שעות מ-data/manual/<project_id>/ ל-Neon. בטוח
להרצה חוזרת (idempotent) — שורות עם row_hash שכבר קיים מדולגות
(ON CONFLICT DO NOTHING).

דרישות:
    • NEON_DATABASE_URL מוגדר (env או secrets.toml).
    • psycopg מותקן (pip install "psycopg[binary]").

הרצה:
    set NEON_DATABASE_URL=postgres://...     (Windows)
    export NEON_DATABASE_URL=postgres://...  (Linux/Mac)
    python scripts/migrate_manual_to_neon.py

כלי כתיבה: מוסיף ל-Neon בלבד. אינו מוחק או משנה קבצים מקומיים.
"""
from __future__ import annotations

import sys
from pathlib import Path

# אפשר הרצה ישירה — הוסף את שורש הפרויקט ל-path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# כפה פלט UTF-8 (קונסול Windows ברירת-מחדל cp1255 משבש עברית).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pipeline  # noqa: E402
from core import cloud_db, manual_store  # noqa: E402


def main() -> int:
    print("מיגרציית הזנות ידניות → Neon")
    print("=" * 56)

    if not cloud_db.is_configured():
        print("[!] NEON_DATABASE_URL לא מוגדר. הגדר אותו והרץ שוב.")
        return 1

    if not cloud_db.ensure_schema():
        print("[!] יצירת הסכמה ב-Neon נכשלה — בדוק את מחרוזת החיבור.")
        return 1
    print("[ok] סכמת Neon מוכנה.")

    total_rows = 0
    total_saved = 0
    projects = pipeline.list_available_projects()
    for proj in projects:
        pid = proj["project_id"]
        pname = proj.get("project_name", pid)
        for kind in ("solar", "hours"):
            store = manual_store.load_store(pid, kind)
            if store.empty:
                continue
            # ודא עמודות hash/month (מאגרים ישנים אולי חסרים) — חשב מחדש
            need = {"row_hash", "key_hash", "month"}
            if not need.issubset(store.columns):
                prepared = manual_store.prepare_incoming(kind, store)
                store = prepared
            total_rows += len(store)
            res = cloud_db.save_entries(
                pid, kind, store, mode="add_new",
                source_file="migration", project_name=pname)
            if res.get("neon_saved"):
                saved = res.get("neon_verified_rows", 0)
                total_saved += len(store)
                print(f"  • {pid}/{kind}: {len(store):,} שורות נשלחו · "
                      f"במאגר Neon: {res.get('neon_store_after', 0):,} "
                      f"(אומתו {saved:,})")
            else:
                print(f"  [!] {pid}/{kind}: שמירה נכשלה — {res.get('error', 'לא ידוע')}")

    print("=" * 56)
    print(f"סה\"כ: {total_rows:,} שורות עובדו · {total_saved:,} נשלחו ל-Neon.")
    print("(שורות כפולות לפי row_hash דולגו אוטומטית — בטוח להריץ שוב.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
