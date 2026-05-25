"""בונה data/fuel_rules.xlsx עם הסכמה המורחבת.

עמודות:
    priority             - סדר התאמה (נמוך = קודם)
    account_num          - חשבון מדויק (חובה)
    description_keyword  - מילת מפתח בפרטים (ריק = "התאם תמיד")
    main_category        - קטגוריה ראשית (תמיד "דלק ואנרגיה")
    sub_category         - תת-קטגוריה (סולר צמ"ה / סולר רכבים / וכו')
    equipment_group      - קבוצת כלי (צמ"ה / רכב / משאית / אחר)
    fuel_type            - סוג דלק (סולר / בנזין / חשמל / לא מסווג)
    confidence           - high / medium / low
    note                 - הסבר חופשי

לוגיקה ב-categorizer:
    1. מסנן את כל הכללים לפי account_num.
    2. ממיין לפי priority עולה.
    3. עובר עליהם - first match wins. כלל ללא keyword = catch-all.
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path

# (priority, account_num, description_keyword, main_category, sub_category,
#  equipment_group, fuel_type, confidence, note)
ROWS = [
    # ── חשבון 74327: סולר צמ"ה (תמיד, לא תלוי בתיאור) ──
    (10, 74327, "", "דלק ואנרגיה", "סולר צמ\"ה", "צמ\"ה", "סולר",
     "high", "חשבון 74327 = סולר צמ\"ה אוטומטית"),

    # ── חשבון 74317: לפי תיאור ──
    # קודמת: טעינת רכב חשמלי (4 keywords)
    (20, 74317, "טעינת רכב חשמלי", "דלק ואנרגיה", "טעינת חשמל רכבים",
     "רכב", "חשמל", "high", "תיאור כולל 'טעינת רכב חשמלי'"),
    (20, 74317, "רכב חשמלי", "דלק ואנרגיה", "טעינת חשמל רכבים",
     "רכב", "חשמל", "high", "תיאור כולל 'רכב חשמלי'"),
    (20, 74317, "אפקון", "דלק ואנרגיה", "טעינת חשמל רכבים",
     "רכב", "חשמל", "high", "ספק אפקון - תחבורה חשמלית"),
    (20, 74317, "תחבורה חשמלית", "דלק ואנרגיה", "טעינת חשמל רכבים",
     "רכב", "חשמל", "high", "תיאור כולל 'תחבורה חשמלית'"),

    # אז: בנזין
    (30, 74317, "בנזין", "דלק ואנרגיה", "בנזין רכבים",
     "רכב", "בנזין", "high", "תיאור כולל 'בנזין'"),

    # אז: סולר
    (40, 74317, "סולר", "דלק ואנרגיה", "סולר רכבים",
     "רכב", "סולר", "high", "תיאור כולל 'סולר'"),

    # אחרון: דלק כללי (catch-all עם דלק בלי פירוט)
    (80, 74317, "דלק", "דלק ואנרגיה", "דלק לא מסווג",
     "רכב", "לא מסווג", "low", "תיאור כולל 'דלק' בלי פירוט סוג"),

    # ── catch-all לחשבון 74317: כל מה שלא תפס keyword קודם ──
    (99, 74317, "", "דלק ואנרגיה", "דלק לא מסווג",
     "רכב", "לא מסווג", "low", "לא נמצאה מילת מפתח מזהה"),

    # ── חשבון 74331: שמנים/אוריאה (לא דלק, אבל קשור לאחזקה) ──
    (10, 74331, "", "אחזקת כלים", "שמנים/אוריאה",
     "צמ\"ה", "לא רלוונטי", "high", "שמן/אוריאה - לא דלק"),
]


def main() -> None:
    df = pd.DataFrame(
        ROWS,
        columns=["priority", "account_num", "description_keyword",
                  "main_category", "sub_category", "equipment_group",
                  "fuel_type", "confidence", "note"],
    )
    df["account_num"] = df["account_num"].astype("Int64")
    out = Path(__file__).resolve().parent.parent / "data" / "fuel_rules.xlsx"
    df.to_excel(out, index=False, engine="openpyxl")
    print(f"Wrote {out}")
    print(f"  rules: {len(df)}")
    print(f"  accounts covered: {df['account_num'].nunique()}")


if __name__ == "__main__":
    main()
