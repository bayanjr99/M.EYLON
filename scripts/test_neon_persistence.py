"""בדיקות קבלה ל-Neon — מריץ את התרחישים הקריטיים מקצה-לקצה.

מטרה: לוודא לפני שסומכים על השמירה הקבועה שכל הדרישות עובדות:
    1. הזנת סולר ידנית נשמרת ל-Neon ונקראת חזרה.
    2. הזנת שעות ידנית נשמרת ל-Neon ונקראת חזרה.
    3. הנתונים שורדים "ריענון" (קריאה חוזרת בחיבור חדש).
    4. אין כפילויות — שמירה חוזרת של אותן שורות לא מגדילה את המאגר.
    5. replace_month מחליף חודש — אך אם הקלט ריק/כושל, לא מוחק קיים.
    6. כל שמירה נרשמת ל-manual_import_log עם batch_id.

הרצה (עם פרויקט בדיקה ייעודי — לא נוגע בנתונים אמיתיים):
    set NEON_DATABASE_URL=postgres://...   (Windows)
    python scripts/test_neon_persistence.py

הסקריפט משתמש ב-project_id ייעודי "__neon_test__" ומנקה אותו בסוף.
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

import pandas as pd  # noqa: E402

from core import cloud_db, manual_store  # noqa: E402

TEST_PID = "__neon_test__"
_passed = 0
_failed = 0


def _check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "[ok]" if cond else "[FAIL]"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def _solar(rows: list[dict]) -> pd.DataFrame:
    return manual_store.prepare_incoming("solar", pd.DataFrame(rows))


def _hours(rows: list[dict]) -> pd.DataFrame:
    return manual_store.prepare_incoming("hours", pd.DataFrame(rows))


def main() -> int:
    print("בדיקות קבלה ל-Neon")
    print("=" * 56)
    if not cloud_db.is_configured():
        print("[!] NEON_DATABASE_URL לא מוגדר.")
        return 1
    if not cloud_db.is_available():
        print("[!] לא ניתן להתחבר ל-Neon — בדוק את מחרוזת החיבור.")
        return 1
    print("[ok] חיבור ל-Neon תקין.\n")

    # ניקוי מצב קודם של פרויקט הבדיקה
    cloud_db.delete_project_kind(TEST_PID, "solar")
    cloud_db.delete_project_kind(TEST_PID, "hours")

    # ── 1. סולר: שמירה + קריאה חוזרת ──
    print("1+2. שמירת סולר/שעות + קריאה חוזרת")
    s1 = _solar([
        {"date": "01/05/2026", "license_num": 11, "supplier": "פז",
         "invoice_num": "A1", "liters": 100, "amount": 700},
        {"date": "03/05/2026", "license_num": 12, "supplier": "דלק",
         "invoice_num": "A2", "liters": 50, "amount": 360},
    ])
    r = cloud_db.save_entries(TEST_PID, "solar", s1, mode="add_new",
                              project_name="בדיקה")
    _check("שמירת 2 שורות סולר", r.get("neon_verified_ok") and r.get("neon_store_after") == 2,
           f"store_after={r.get('neon_store_after')}, batch={r.get('batch_id')}")
    _check("נרשם batch_id", bool(r.get("batch_id")))

    h1 = _hours([
        {"date": "01/05/2026", "employee_name": "דני", "site": "אתר א",
         "regular_hours": 8, "total_hours": 8},
    ])
    rh = cloud_db.save_entries(TEST_PID, "hours", h1, mode="add_new",
                               project_name="בדיקה")
    _check("שמירת שורת שעות", rh.get("neon_verified_ok") and rh.get("neon_store_after") == 1)

    # ── 3. "ריענון": קריאה בחיבור חדש ──
    print("\n3. שרידות (קריאה חוזרת בחיבור חדש)")
    back = cloud_db.load_entries(TEST_PID, "solar")
    _check("קריאת 2 שורות סולר חזרה", len(back) == 2, f"נקראו {len(back)}")
    _check("payload נשמר (liters)", "liters" in back.columns and
           float(pd.to_numeric(back["liters"], errors="coerce").sum()) == 150.0)

    # ── 4. ללא כפילויות ──
    print("\n4. מניעת כפילויות (שמירה חוזרת של אותן שורות)")
    r2 = cloud_db.save_entries(TEST_PID, "solar", s1, mode="add_new",
                               project_name="בדיקה")
    _check("המאגר נשאר 2 (לא 4)", r2.get("neon_store_after") == 2,
           f"store_after={r2.get('neon_store_after')}")

    # ── 5. replace_month + בטיחות קלט ריק ──
    print("\n5. replace_month + בטיחות")
    s_may_new = _solar([
        {"date": "10/05/2026", "license_num": 99, "supplier": "סונול",
         "invoice_num": "B1", "liters": 30, "amount": 210},
    ])
    r3 = cloud_db.save_entries(TEST_PID, "solar", s_may_new,
                               mode="replace_month", target_month="05-2026",
                               project_name="בדיקה")
    after = cloud_db.load_entries(TEST_PID, "solar")
    _check("05-2026 הוחלף לשורה אחת", len(after) == 1 and r3.get("neon_verified_ok"),
           f"נשארו {len(after)} שורות")
    # קלט ריק לא מוחק (save_entries לא נקרא עם valid ריק — מדמים זאת)
    r_empty = cloud_db.save_entries(TEST_PID, "solar",
                                    manual_store.empty_frame("solar"),
                                    mode="replace_month", target_month="05-2026")
    after2 = cloud_db.load_entries(TEST_PID, "solar")
    _check("קלט ריק לא מחק את החודש", len(after2) == 1 and not r_empty.get("neon_saved"),
           f"נשארו {len(after2)} שורות")

    # ── 6. לוג יבוא ──
    print("\n6. manual_import_log")
    log = cloud_db.read_import_log(TEST_PID)
    _check("נרשמו שורות לוג", not log.empty and "batch_id" in log.columns,
           f"{len(log)} רשומות")

    # ── ניקוי ──
    cloud_db.delete_project_kind(TEST_PID, "solar")
    cloud_db.delete_project_kind(TEST_PID, "hours")
    print("\n[ok] ניקוי פרויקט הבדיקה הושלם.")

    print("=" * 56)
    print(f"סה\"כ: {_passed} עברו · {_failed} נכשלו.")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
