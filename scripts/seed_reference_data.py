"""סקריפט חד-פעמי ליצירת קבצי הreference XLSX:
    data/projects_registry.xlsx
    data/category_mapping.xlsx
    data/tools_registry.xlsx

הרצה: python scripts/seed_reference_data.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def seed_projects_registry() -> None:
    """פרויקט אחד לדוגמה - ראשון לציון."""
    df = pd.DataFrame([
        {
            "project_id": "rishon_letzion",
            "project_name": "ראשון לציון",
            "site_name": "ראשון לציון",   # לסינון solar.xlsx
            "status": "active",
            "start_date": "2025-01-01",
            "notes": "פרויקט תשתיות בדרום העיר",
        },
    ])
    df.to_excel(DATA_DIR / "projects_registry.xlsx", index=False)
    print("Created projects_registry.xlsx")


def seed_category_mapping() -> None:
    """מיפוי חשבונות → קטגוריות."""
    rows = [
        (927,     "הכנסות",                "הכנסות",          ""),
        (951,     "הכנסות",                "הכנסות",          ""),
        (7367,    "הכנסות זקופות",         "הכנסות",          "זקופות"),
        (74327,   'סולר צמ"ה',             "סולר וצמ\"ה",     "סולר"),
        (7366,    "הוצאות שכר עבודה",      "שכר עבודה",       "שכר ישראלי"),
        (74326,   "שכר עובדים זרים",       "שכר עבודה",       "שכר זרים"),
        (74311,   "קבלני משנה",            "קבלני משנה",      ""),
        (74310,   "מים וביוב",             "תשתיות",          "מים וביוב"),
        (74330,   "ניהול ויעוץ",           "ניהול",           ""),
        (74399,   "הוצאות חריגות",         "הוצאות חריגות",   ""),
        (7439957, "הוצאות חריגות",         "הוצאות חריגות",   ""),
    ]
    df = pd.DataFrame(rows, columns=["account_num", "account_name", "category", "subcategory"])
    df.to_excel(DATA_DIR / "category_mapping.xlsx", index=False)
    print("Created category_mapping.xlsx")


def seed_tools_registry() -> None:
    """24 כלים עם תקני צריכת סולר."""
    rows = [
        (230831, "באגר דוסן",            "באגר זחל בינוני", 15, 22),
        (231953, "באגר 352",             "באגר זחל גדול",   22, 30),
        (231952, "באגר טלאור",           "באגר זחל בינוני", 15, 22),
        (181138, "באגר וולבו 380",       "באגר זחל גדול",   22, 30),
        (244031, "באגר וולו",            "באגר זחל בינוני", 15, 22),
        (168792, "שופל קטרפילר 966M",    "שופל גדול",       15, 22),
        (181478, "שופל L150",            "שופל גדול",       15, 22),
        (190157, "שופל שרשרת",           "שופל שרשרת",      18, 28),
        (180877, "שופל 120",             "שופל קטן",        10, 14),
        (168351, "נפה R230",             "נפה R230",        10, 16),
        (221150, "מכבש",                 "מכבש",             8, 12),
        (221287, "מכבש 120",             "מכבש",             8, 12),
        (244158, "מכבש 75",              "מכבש",             8, 12),
        (169590, "פירקית מכלית מים",     "פירקית",          12, 18),
        (139797, "פירקית",               "פירקית",          12, 18),
        (139815, "פירקית",               "פירקית",          12, 18),
        (244038, "פירקית",               "פירקית",          12, 18),
        (244039, "פירקית",               "פירקית",          12, 18),
        (244024, "פירקית וולוו",         "פירקית",          12, 18),
        (244025, "פירקית וולוו",         "פירקית",          12, 18),
        (231699, "זחל עיסא",             "זחל",             18, 25),
        (225475, "מיני מחפרון",          "מיני מחפרון",      5, 10),
        (225476, "בובקט",                "בובקט",            6, 10),
        (401931, "גנרטור",               "גנרטור 100 KVA",  12, 18),
    ]
    df = pd.DataFrame(rows, columns=["license_num", "tool_name", "tool_type", "norm_low", "norm_high"])
    df.to_excel(DATA_DIR / "tools_registry.xlsx", index=False)
    print("Created tools_registry.xlsx")


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seed_projects_registry()
    seed_category_mapping()
    seed_tools_registry()
    print("\nDone. All reference XLSX files created in:", DATA_DIR)
