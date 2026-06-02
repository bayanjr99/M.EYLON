"""סנכרון רישום הפרויקטים המקומי (projects_registry.xlsx) אל Neon.

מתי להשתמש
----------
בדרך-כלל אין צורך: עריכת פרויקט *באתר* נשמרת ל-Neon אוטומטית. הסקריפט
הזה נועד למקרה שבו ערכת/הוספת פרויקטים *מקומית* (ישירות ב-xlsx או דרך
האפליקציה המקומית) ואתה רוצה לדחוף אותם לענן כדי שיופיעו באתר.

מה הוא עושה
-----------
קורא את ``data/projects_registry.xlsx`` ועושה upsert של כל שורה ל-Neon
(טבלת ``projects_registry``), עם אימות קריאה-חוזרת לכל שורה. אינו מוחק
דבר — רק מוסיף/מעדכן.

הרצה
----
    python scripts/sync_registry_to_neon.py
    python -m scripts.sync_registry_to_neon

דורש שמשתנה הסביבה ``NEON_DATABASE_URL`` יהיה מוגדר.
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

from core import cloud_db, project_store  # noqa: E402


def main() -> int:
    print("סנכרון projects_registry → Neon")
    if not cloud_db.is_configured():
        print("[!] NEON_DATABASE_URL לא מוגדר — אין יעד לסנכרון.")
        print("    הגדר את משתנה הסביבה והרץ שוב.")
        return 1
    if not cloud_db.is_available():
        print("[!] Neon מוגדר אך לא ניתן להתחבר (רשת/אישורים/timeout).")
        return 1

    df = project_store._load_registry_xlsx()
    if df.empty:
        print("[i] אין פרויקטים ב-xlsx לסנכרן.")
        return 0

    print(f"דוחף {len(df)} פרויקטים ל-Neon...")
    res = cloud_db.sync_projects_from_df(df)
    print(f"  אומתו: {res['verified']}/{res['total']}")
    if res["failed"]:
        print(f"[!] נכשלו (לא אומתו): {', '.join(res['failed'])}")
        return 1
    print("[ok] כל הפרויקטים סונכרנו ואומתו ב-Neon.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
