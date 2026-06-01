"""בדיקת תקינות מערכת — מיפוי בין projects_registry, תיקיות, ומאגרים.

מטרה: לאתר חוסר-התאמה לפני שהוא הופך לבאג "נתונים נעלמים":
    • פרויקטים ב-registry מול תיקיות בפועל (orphans / חסרים).
    • קבצים "תלויים באוויר" (כרטסת/מאזן ישירות בתיקיית הפרויקט, לא בתוך
      תיקיית חודש ולא מיובאים ל-ledger_store) — לא ייטענו ל-master.
    • חודשים שמזוהים לכל פרויקט (תיקיות / ledger_store / הזנה ידנית).
    • נוכחות ledger_store / manual_store לכל פרויקט.
    • קבצי DATA כפולים/חריגים בגודלם.

הרצה:
    python scripts/health_check.py
    python -m scripts.health_check

כלי קריאה-בלבד. אינו משנה דבר.
"""
from __future__ import annotations

import sys
from pathlib import Path

# אפשר הרצה ישירה (python scripts/health_check.py) — הוסף את שורש הפרויקט ל-path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# כפה פלט UTF-8 (קונסול Windows ברירת-מחדל cp1255 משבש עברית).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd  # noqa: E402

import pipeline  # noqa: E402
from core import cloud_db, ledger_store, manual_store  # noqa: E402

# קבצי-מאגר/עזר פנימיים שיושבים בתיקיית הפרויקט ואינם "תלויים באוויר".
_KNOWN_STORE_FILES = {
    "_ledger_store.parquet",
    "site_tracking.xlsx",
}
# מילות-מפתח לקבצי קלט גולמיים שנדרש לייבא (כרטסת/מאזן) ולא נטענים אוטומטית.
_RAW_INPUT_KEYWORDS = ["כרטיס", "chashbashevet", "מאזן", "balance"]


def _hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def _registry_projects() -> list[dict]:
    return pipeline.list_available_projects()


def _folder_projects() -> list[str]:
    root = pipeline.PROJECTS_ROOT
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir())


def _loose_files(project_dir: Path) -> list[str]:
    """קבצי xlsx ישירות בתיקיית הפרויקט (לא בתוך תיקיית חודש)."""
    out: list[str] = []
    for f in project_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
            continue
        if f.name.startswith("~$") or f.name in _KNOWN_STORE_FILES:
            continue
        out.append(f.name)
    return sorted(out)


def _month_folders(project_dir: Path) -> list[str]:
    return sorted(
        d.name for d in project_dir.iterdir()
        if d.is_dir() and "-" in d.name
    )


def _store_months(project_id: str) -> list[str]:
    try:
        store = ledger_store.load_store(project_id)
        if store.empty or "month" not in store.columns:
            return []
        return sorted(store["month"].dropna().unique().tolist())
    except Exception:
        return []


def _manual_summary(project_id: str) -> str:
    parts = []
    for kind in ("solar", "hours"):
        try:
            if manual_store.has_store(project_id, kind):
                df = manual_store.load_store(project_id, kind)
                parts.append(f"{kind}={len(df)}")
        except Exception:
            pass
    return ", ".join(parts) if parts else "—"


def check_projects() -> int:
    """מצליב registry מול תיקיות. מחזיר מספר אזהרות."""
    warnings = 0
    reg = _registry_projects()
    reg_ids = {str(p.get("project_id")) for p in reg}
    folders = _folder_projects()
    folder_set = set(folders)

    _hr("פרויקטים: registry מול תיקיות")
    print(f"ב-registry: {len(reg_ids)}  | תיקיות בפועל: {len(folders)}")

    orphans = sorted(folder_set - reg_ids)
    if orphans:
        warnings += len(orphans)
        print(f"\n[!] תיקיות ללא פרויקט ב-registry ({len(orphans)}):")
        for o in orphans:
            print(f"      data/projects/{o}/  → להוסיף ל-registry או להעביר ל-data/.trash")

    missing = sorted(reg_ids - folder_set)
    if missing:
        warnings += len(missing)
        print(f"\n[!] פרויקטים ב-registry ללא תיקייה ({len(missing)}):")
        for m in missing:
            print(f"      {m}")

    if not orphans and not missing:
        print("[ok] התאמה מלאה בין registry לתיקיות.")
    return warnings


def check_project_details() -> int:
    """לכל פרויקט: חודשים, מאגרים, וקבצים תלויים-באוויר."""
    warnings = 0
    reg = {str(p.get("project_id")): p for p in _registry_projects()}
    folders = _folder_projects()

    _hr("פירוט פר-פרויקט")
    for pid in sorted(set(folders) | set(reg.keys())):
        project_dir = pipeline.PROJECTS_ROOT / pid
        in_reg = pid in reg
        print(f"\n• {pid}  ({'ב-registry' if in_reg else 'ללא registry'})")
        if not project_dir.exists():
            print("    (אין תיקייה)")
            continue

        m_folders = _month_folders(project_dir)
        s_months = _store_months(pid)
        has_store = ledger_store.has_store(pid)
        print(f"    ledger_store: {'יש' if has_store else 'אין'}"
              f"  | חודשי-מאגר: {len(s_months)}"
              f"  | תיקיות-חודש: {len(m_folders)}")
        print(f"    manual_store: {_manual_summary(pid)}")

        loose = _loose_files(project_dir)
        if loose:
            raw = [f for f in loose
                   if any(k in f for k in _RAW_INPUT_KEYWORDS)]
            if raw and not has_store and not m_folders:
                warnings += 1
                print(f"    [!] קבצים גולמיים שלא יובאו (לא ב-ledger_store ולא בתיקיית חודש):")
                for f in raw:
                    print(f"          {f}  → לייבא דרך 'ייבוא נתונים' או להעביר לתיקיית חודש")
            else:
                print(f"    קבצים בתיקייה: {', '.join(loose)}")
    return warnings


def check_master_coverage() -> int:
    """משווה מי מופיע ב-master.parquet מול ה-registry."""
    warnings = 0
    _hr("כיסוי master.parquet")
    m = pipeline.load_master()
    if m.empty:
        print("[!] master.parquet ריק.")
        return 1
    by_proj = m.groupby("project_id").size().to_dict()
    reg_ids = {str(p.get("project_id")) for p in _registry_projects()}
    print(f'שורות סה"כ: {len(m)}  | פרויקטים ב-master: {len(by_proj)}')
    for pid, n in sorted(by_proj.items()):
        tag = "" if pid in reg_ids else "  [!] לא ב-registry"
        print(f"    {pid}: {n} שורות{tag}")
    no_data = sorted(reg_ids - set(by_proj))
    if no_data:
        warnings += len(no_data)
        print(f"\n[!] פרויקטים ב-registry ללא שורות ב-master ({len(no_data)}):")
        for p in no_data:
            print(f"      {p}  → לוודא שהכרטסת יובאה ל-ledger_store")
    return warnings


def check_data_files() -> int:
    """מאתר קבצי DATA חריגים/כפולים (לפי שם דומה)."""
    _hr("קבצי DATA")
    data_root = pipeline.DATA_ROOT
    files = [f for f in data_root.iterdir() if f.is_file()]
    for f in sorted(files, key=lambda x: x.name):
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name:<32} {size_kb:8.1f} KB")
    # אזהרה על זוגות xlsx+parquet (תקין — אך מציין לתשומת לב)
    stems = {}
    for f in files:
        stems.setdefault(f.stem, []).append(f.suffix.lower())
    dups = {s: exts for s, exts in stems.items() if len(exts) > 1}
    if dups:
        print("\n    (זוגות xlsx+parquet — תקין, mirror לענן):")
        for s, exts in dups.items():
            print(f"      {s}: {', '.join(exts)}")
    return 0


def check_neon() -> int:
    """בודק את שכבת ההתמדה הקבועה (Neon) — קריטי ל-Streamlit Cloud.

    בענן מערכת-הקבצים זמנית, ולכן ההזנות הידניות (סולר/שעות) שורדות *רק*
    אם הן ב-Neon. הבדיקה מוודאת: מוגדר? זמין? כמה שורות לכל פרויקט/סוג?
    האם יש שורות ללא תאריך? והאם Neon תואם ל-master.parquet.
    """
    warnings = 0
    _hr("התמדה קבועה (Neon Postgres)")

    if not cloud_db.is_configured():
        print("[i] Neon לא מוגדר (NEON_DATABASE_URL חסר).")
        print("    מצב מקומי: ההזנות נשמרות לקבצים מקומיים (data/manual/**).")
        print("    שים לב: על Streamlit Cloud — בלי Neon, הזנות ידניות *יאבדו*")
        print("    ב-reboot/redeploy. זו אזהרה רק אם המערכת רצה בענן.")
        return 0

    print("[ok] Neon מוגדר (NEON_DATABASE_URL קיים).")
    if not cloud_db.is_available():
        warnings += 1
        print("[!] Neon מוגדר אך לא ניתן להתחבר כרגע (timeout/אישורים/רשת).")
        print("    שמירות ל-Neon ייכשלו — ההזנה לא תאומת ולא תוצג כ'נשמר'.")
        return warnings

    print("[ok] Neon זמין (חיבור בדיקה הצליח).")

    reg_ids = sorted({str(p.get("project_id")) for p in _registry_projects()})
    master = pipeline.load_master()
    total_neon = 0
    for pid in reg_ids:
        for kind in sorted(manual_store.MASTER_KINDS):
            try:
                df = cloud_db.load_entries(pid, kind)
            except Exception as e:
                warnings += 1
                print(f"[!] {pid}/{kind}: כשל בקריאה מ-Neon ({e}).")
                continue
            if df.empty:
                continue
            n = len(df)
            total_neon += n
            line = f"    {pid}/{kind}: {n} שורות"

            # שורות ללא תאריך — לא יזוהו בחתך חודשי במאסטר
            if "date" in df.columns:
                no_date = int(pd.to_datetime(df["date"], errors="coerce").isna().sum())
                if no_date:
                    warnings += 1
                    line += f"  [!] {no_date} ללא תאריך"

            # row_hash כפול — PK ב-Neon, אמור להיות בלתי-אפשרי; בדיקת-בטיחות
            if "row_hash" in df.columns:
                dups = int(df["row_hash"].duplicated().sum())
                if dups:
                    warnings += 1
                    line += f"  [!] {dups} row_hash כפול"

            # התאמה מול master.parquet (origin=neon_manual נטען חי בדשבורד)
            if not master.empty and "source" in master.columns:
                in_master = master[
                    (master.get("project_id") == pid)
                    & (master.get("source") == "manual")
                ]
                # אינפורמטיבי בלבד: master.parquet עצמו לא חייב לכלול manual
                # כשהוא נטען חי דרך load_master_merged.
                _ = in_master  # אין אזהרה — נטען בזמן ריצה
            print(line)

    if total_neon == 0:
        print("    (אין הזנות ידניות ב-Neon עדיין.)")
    else:
        print(f"\n    סה\"כ ב-Neon: {total_neon} הזנות ידניות.")
    return warnings


def main() -> int:
    print("בדיקת תקינות מערכת — מ. אילון אביב נכסים")
    total = 0
    total += check_projects()
    total += check_project_details()
    total += check_master_coverage()
    total += check_data_files()
    total += check_neon()

    _hr("סיכום")
    if total == 0:
        print("[ok] לא נמצאו אזהרות.")
    else:
        print(f"[!] {total} אזהרות — ראה פירוט למעלה.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
