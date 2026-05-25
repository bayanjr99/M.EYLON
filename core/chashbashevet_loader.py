"""טעינת כרטיס הנהלה ממחשבשבת.

מבנה הקובץ (XLSX מיוצא ממחשבשבת):
- שורות כותרת בראש הקובץ - יש לדלגן.
- כל חשבון מתחיל בשורת כותרת:
    עמודה A = שם החשבון, עמודה B = מספר חשבון.
- אחריה שורות תנועה:
    עמודה I = תאריך אסמכתא (datetime)
    עמודה J = תאריך ערך (datetime) ← מזהה שורת תנועה
    עמודה M = פרטים (string)
    עמודה O = חובה (number)
    עמודה P = זכות (number)
- בסוף קבוצת תנועות יש שורת "סה"כ" - יש לדלג.

חשבונות הכנסה (נטו הפוך - credit מינוס debit):
    INCOME_ACCOUNTS = {927, 951, 7367}
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


INCOME_ACCOUNTS: set[int] = {927, 951, 7367}

# חשבונות שכר ונלוות - בדרך כלל אין להם "ספק" אמיתי
# (התיאור הוא "שכ"ע 12/25" וכו'). השמירה: אם התיאור _נראה_ כקוד פנימי
# (מתחיל ב-שכ"ע / מכיל ##/## בלבד) נדכא; אחרת ניתן ייחוס נורמלי כי
# יש ספקי שכר אמיתיים (סוכנויות כ"א, ביטוח לאומי וכו').
SALARY_ACCOUNTS: set[int] = {
    7366, 74326, 7368, 7369, 7370, 7371,
}

# regex לתיאור פנימי של שכר: "שכ"ע MM/YY" או "שכר MM/YY"
import re as _re
_INTERNAL_SALARY_DESC = _re.compile(r"^שכ[\"']?ע?\s*\d{1,2}/\d{2,4}")

# מיקומי עמודות (0-indexed). עמודה A = 0, B = 1 וכו'.
COL_ACCOUNT_NAME = 0   # A
COL_ACCOUNT_NUM = 1    # B
COL_DATE_REF = 8       # I - תאריך אסמכתא
COL_DATE_VALUE = 9     # J - תאריך ערך (מזהה תנועה)
COL_DETAILS = 12       # M - פרטים
COL_DEBIT = 14         # O - חובה
COL_CREDIT = 15        # P - זכות

# סכמת ה-DataFrame המוחזר
OUTPUT_COLS = [
    "account_num", "account_name", "date", "details",
    "debit", "credit", "amount", "supplier",
    # 7 שדות סיווג מ-classify_transaction
    "account_type", "main_category", "sub_category",
    "net_amount", "signed_amount", "is_credit_note",
    "classification_confidence", "classification_note",
]

_TOTAL_KEYWORDS = ("סה\"כ", "סהכ", "סה'כ", "יתרה")


def load_chashbashevet(file_path: str | Path) -> pd.DataFrame:
    """טוען קובץ כרטיס הנהלה מ-XLSX אל DataFrame מנורמל.

    Args:
        file_path: נתיב מלא לקובץ chashbashevet.xlsx.

    Returns:
        DataFrame עם העמודות:
            account_num, account_name, date, details,
            debit, credit, amount, supplier.
        amount = debit - credit (להוצאות), credit - debit (להכנסות).
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("chashbashevet file not found: %s", path)
        return pd.DataFrame(columns=OUTPUT_COLS)

    try:
        raw = pd.read_excel(path, header=None, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read chashbashevet xlsx: %s", e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    records: list[dict] = []
    current_account_num: int | None = None
    current_account_name: str = ""

    for _, row in raw.iterrows():
        # 1) בדיקה אם זו שורת כותרת חשבון חדש (יש מספר חשבון בעמודה B)
        acct_num = _to_int(row.iloc[COL_ACCOUNT_NUM]) if len(row) > COL_ACCOUNT_NUM else None
        if acct_num is not None and not _is_transaction_row(row):
            current_account_num = acct_num
            current_account_name = _safe_str(row.iloc[COL_ACCOUNT_NAME])
            continue

        # 2) דילוג על שורת "סה"כ" / "יתרה"
        first_cell = _safe_str(row.iloc[COL_ACCOUNT_NAME]) if len(row) > COL_ACCOUNT_NAME else ""
        if any(kw in first_cell for kw in _TOTAL_KEYWORDS):
            continue

        # 3) שורת תנועה
        if current_account_num is None or not _is_transaction_row(row):
            continue

        date_val = pd.to_datetime(row.iloc[COL_DATE_VALUE], errors="coerce")
        if pd.isna(date_val):
            continue

        details = _safe_str(row.iloc[COL_DETAILS]) if len(row) > COL_DETAILS else ""
        debit = _to_float(row.iloc[COL_DEBIT]) if len(row) > COL_DEBIT else 0.0
        credit = _to_float(row.iloc[COL_CREDIT]) if len(row) > COL_CREDIT else 0.0

        if current_account_num in INCOME_ACCOUNTS:
            amount = credit - debit
            amount = -abs(amount) if amount != 0 else 0.0
        else:
            amount = debit - credit

        # ספק: דכא רק אם זה חשבון שכר ובתיאור הוא קוד פנימי ("שכ"ע MM/YY").
        # אם בחשבון שכר יש ספק אמיתי (ינאי פרסונל וכו') - נשמור אותו.
        if current_account_num in SALARY_ACCOUNTS and _INTERNAL_SALARY_DESC.match(details):
            supplier = ""
        else:
            supplier = _extract_supplier(details)

        # סיווג מלא: account_type / main_category / sub_category / net_amount /
        # is_credit_note / confidence / note — לפי המפרט החדש
        from core.categorizer import classify_transaction
        cls = classify_transaction(
            current_account_num, current_account_name, details, debit, credit,
        )

        records.append({
            "account_num": current_account_num,
            "account_name": current_account_name,
            "date": date_val,
            "details": details,
            "debit": debit,
            "credit": credit,
            "amount": amount,
            "supplier": supplier,
            # שדות חדשים מ-classify_transaction
            "account_type": cls["account_type"],
            "main_category": cls["main_category"],
            "sub_category": cls["sub_category"],
            "net_amount": cls["net_amount"],
            "signed_amount": cls["signed_amount"],
            "is_credit_note": cls["is_credit_note"],
            "classification_confidence": cls["classification_confidence"],
            "classification_note": cls["classification_note"],
        })

    df = pd.DataFrame(records, columns=OUTPUT_COLS)
    logger.info("Loaded %d transactions from %s", len(df), path.name)
    return df


def _extract_supplier(details: str) -> str:
    """מחלץ שם ספק מתוך שדה הפרטים.

    בדרך כלל החלק לפני המקף הראשון. דוגמאות:
        "אלון תדלוקים - חשבונית 12345" → "אלון תדלוקים"
        "פז חברת נפט בעמ"               → "פז חברת נפט בעמ"
    """
    if not isinstance(details, str) or not details.strip():
        return ""
    if "-" in details:
        return details.split("-", 1)[0].strip()
    return details.strip()


def _is_transaction_row(row: pd.Series) -> bool:
    """בודק אם שורה היא שורת תנועה (יש לה תאריך ערך בעמודה J)."""
    if len(row) <= COL_DATE_VALUE:
        return False
    val = row.iloc[COL_DATE_VALUE]
    if pd.isna(val):
        return False
    return not pd.isna(pd.to_datetime(val, errors="coerce"))


def _safe_str(val) -> str:
    """המרה בטוחה ל-string, מטפלת ב-NaN."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _to_int(val) -> int | None:
    """המרה ל-int. מחזיר None אם לא ניתן."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _to_float(val) -> float:
    """המרה ל-float. מחזיר 0.0 אם לא ניתן."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
