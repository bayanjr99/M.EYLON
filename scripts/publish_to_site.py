"""הכנת נתוני DATA מקומיים לפרסום באתר (build + sync), ללא git.

רקע
---
האתר (Streamlit Cloud) טוען נתונים מ-GitHub, לא מהמחשב שלך. כדי שעדכון
בקבצי DATA יופיע באתר צריך: (1) לבנות מחדש את master.parquet מהקבצים
הגולמיים; (2) לסנכרן את רישום הפרויקטים ל-Neon; (3) git commit + push.

הסקריפט הזה עושה את שלבים 1-2. את שלב 3 (git) מבצע ``publish_to_site.bat``
או שאתה ידנית. כך פעולות ה-git גלויות ונשלטות.

מה הוא עושה
-----------
1. ``pipeline.build_master()`` — בונה את data/master.parquet מהקבצים
   הגולמיים שבתיקיות הפרויקטים המקומיות.
2. אם NEON_DATABASE_URL מוגדר — דוחף את projects_registry.xlsx ל-Neon
   (כדי שעריכות מקומיות יופיעו באתר).

הרצה
----
    python scripts/publish_to_site.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> int:
    print("פרסום נתונים לאתר — שלב הכנה (build + sync)")

    # ── 1. בניית master.parquet מהקבצים הגולמיים המקומיים ──
    print("\n[1/2] בונה master.parquet מחדש מהקבצים המקומיים...")
    import pipeline
    try:
        master = pipeline.build_master()
        n = len(master) if master is not None else 0
        print(f"      [ok] master.parquet נבנה — {n} שורות.")
    except Exception as e:
        print(f"      [!] בניית master נכשלה: {e}")
        return 1

    # ── 2. סנכרון רישום פרויקטים ל-Neon (אם מוגדר) ──
    print("\n[2/2] מסנכרן רישום פרויקטים ל-Neon...")
    from core import cloud_db, project_store
    if not cloud_db.is_configured():
        print("      [i] Neon לא מוגדר — דילוג (מצב מקומי).")
    elif not cloud_db.is_available():
        print("      [!] Neon מוגדר אך לא זמין — דילוג. בדוק חיבור.")
    else:
        df = project_store._load_registry_xlsx()
        res = cloud_db.sync_projects_from_df(df)
        print(f"      אומתו {res['verified']}/{res['total']} פרויקטים.")
        if res["failed"]:
            print(f"      [!] נכשלו: {', '.join(res['failed'])}")

    print("\n[ok] ההכנה הסתיימה. עכשיו דחוף ל-GitHub כדי שהאתר יתעדכן:")
    print("      git add data/master.parquet data/projects_registry.xlsx data/manual")
    print('      git commit -m "publish: update site data"')
    print("      git push")
    print("\n(או הרץ publish_to_site.bat שעושה את כל זה אוטומטית.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
