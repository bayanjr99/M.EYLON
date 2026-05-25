"""טעינת מאזן בוחן מחשבשבת (קובץ מאזן XX.YY.xlsx).

מבנה הקובץ:
    שורות 0-4: כותרות וכותרת תקופה
    שורה 3: header row עם: מיון / חשבון / שם חשבון / חובה / זכות / הפרש
    שורה 4 ואילך: שורת קבוצה ("פרויקט ראשל"צ") ואחריה שורות חשבון.

הקובץ נשמר מתכנת חשבשבת ישנה שמייצרת styles.xml עם 'borderID' במקום
'borderId' — לכן openpyxl נכשל. פתרון: לבצע XML patch בזיכרון לפני קריאה.

הקובץ הוא end-of-period balance — לא transaction-level.
משמש לתיקוף (reconciliation) שסיכום הכרטיס תואם למאזן.
"""
from __future__ import annotations

import io
import logging
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# מיקומי עמודות בקובץ הגולמי (0-indexed) - אחרי דילוג header
COL_GROUP = 0        # A - שם קבוצה ("פרויקט ראשל"צ")
COL_SORT = 1         # B - מיון
COL_ACCOUNT_NUM = 2  # C - חשבון
COL_ACCOUNT_NAME = 3 # D - שם חשבון
COL_DEBIT = 4        # E - חובה
COL_CREDIT = 5       # F - זכות
COL_DIFF = 6         # G - הפרש

HEADER_ROW = 3  # שורה שבה נמצאות הכותרות

OUTPUT_COLS = ["sort_key", "account_num", "account_name",
               "debit", "credit", "balance", "group"]


def _patch_xlsx_styles(file_path: Path) -> Path:
    """יוצר עותק זמני של ה-xlsx עם תיקון אטריביוטי styles.xml.

    מתקן: borderID → borderId, fillID → fillId, fontID → fontId.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="balance_fix_"))
    out = tmp_dir / file_path.name
    with zipfile.ZipFile(file_path, "r") as zin:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                data = zin.read(item)
                if item.endswith("styles.xml"):
                    data = (data
                            .replace(b"borderID", b"borderId")
                            .replace(b"fillID", b"fillId")
                            .replace(b"fontID", b"fontId"))
                zout.writestr(item, data)
    return out


def load_balance(file_path: str | Path) -> pd.DataFrame:
    """טוען קובץ מאזן בוחן ומחזיר DataFrame מנורמל.

    Returns DataFrame עם: sort_key, account_num, account_name,
    debit, credit, balance, group.
    """
    path = Path(file_path)
    if not path.exists():
        logger.info("balance file not found: %s", path)
        return pd.DataFrame(columns=OUTPUT_COLS)

    # נסיון ראשון - קריאה רגילה (אם הקובץ תקין)
    try:
        raw = pd.read_excel(path, header=None, engine="openpyxl")
    except TypeError as e:
        # XML schema mismatch (borderID/fillID/fontID) — patch and retry
        if "borderID" in str(e) or "fillID" in str(e) or "fontID" in str(e):
            logger.info("Patching xlsx styles for %s", path.name)
            fixed = _patch_xlsx_styles(path)
            try:
                raw = pd.read_excel(fixed, header=None, engine="openpyxl")
            except Exception as e2:
                logger.exception("Failed even after patch: %s", e2)
                return pd.DataFrame(columns=OUTPUT_COLS)
        else:
            logger.exception("Failed to read balance: %s", e)
            return pd.DataFrame(columns=OUTPUT_COLS)
    except Exception as e:
        logger.exception("Failed to read balance: %s", e)
        return pd.DataFrame(columns=OUTPUT_COLS)

    records = []
    current_group = ""
    for i, row in raw.iterrows():
        if i <= HEADER_ROW:
            continue
        # Group row (column A populated, account num empty)
        first_cell = row.iloc[COL_GROUP] if len(row) > COL_GROUP else None
        acct_raw = row.iloc[COL_ACCOUNT_NUM] if len(row) > COL_ACCOUNT_NUM else None
        if pd.notna(first_cell) and isinstance(first_cell, str) and first_cell.strip() and pd.isna(acct_raw):
            current_group = str(first_cell).strip()
            continue
        # Account row (account_num populated)
        if pd.isna(acct_raw):
            continue
        try:
            acct_num = int(float(acct_raw))
        except (TypeError, ValueError):
            continue
        records.append({
            "sort_key": _to_str(row.iloc[COL_SORT]) if len(row) > COL_SORT else "",
            "account_num": acct_num,
            "account_name": _to_str(row.iloc[COL_ACCOUNT_NAME]) if len(row) > COL_ACCOUNT_NAME else "",
            "debit": _to_float(row.iloc[COL_DEBIT]) if len(row) > COL_DEBIT else 0.0,
            "credit": _to_float(row.iloc[COL_CREDIT]) if len(row) > COL_CREDIT else 0.0,
            "balance": _to_float(row.iloc[COL_DIFF]) if len(row) > COL_DIFF else 0.0,
            "group": current_group,
        })

    df = pd.DataFrame(records, columns=OUTPUT_COLS)
    logger.info("Loaded %d balance rows from %s", len(df), path.name)
    return df


def _to_str(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _to_float(val) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, str):
        # Some balance files have strings like "1,234.56"
        try:
            return float(val.replace(",", ""))
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def reconcile_with_ledger(balance_df: pd.DataFrame,
                            ledger_df: pd.DataFrame) -> pd.DataFrame:
    """משווה מאזן (סיכום סוף תקופה) מול תנועות (כרטיס).

    Args:
        balance_df: מ-load_balance(), שורה לכל חשבון.
        ledger_df: מ-load_chashbashevet() — תנועות פרטניות.

    Returns DataFrame עם: account_num, account_name, balance_debit,
    balance_credit, ledger_debit, ledger_credit, debit_diff, credit_diff, status.
    """
    cols = ["account_num", "account_name", "balance_debit", "balance_credit",
            "ledger_debit", "ledger_credit", "debit_diff", "credit_diff", "status"]
    if balance_df.empty:
        return pd.DataFrame(columns=cols)

    # Aggregate ledger per account
    if not ledger_df.empty:
        ledger_agg = ledger_df.groupby("account_num").agg(
            ledger_debit=("debit", "sum"),
            ledger_credit=("credit", "sum"),
        ).reset_index()
    else:
        ledger_agg = pd.DataFrame(columns=["account_num", "ledger_debit", "ledger_credit"])

    merged = balance_df.merge(ledger_agg, on="account_num", how="left").fillna(0)
    merged = merged.rename(columns={"debit": "balance_debit", "credit": "balance_credit"})
    merged["debit_diff"] = (merged["balance_debit"] - merged["ledger_debit"]).round(2)
    merged["credit_diff"] = (merged["balance_credit"] - merged["ledger_credit"]).round(2)

    def _status(r):
        d, c = abs(r["debit_diff"]), abs(r["credit_diff"])
        if d < 0.5 and c < 0.5:
            return "✓ תואם"
        if d > 100 or c > 100:
            return "✗ הפרש משמעותי"
        return "⚠ הפרש קטן"
    merged["status"] = merged.apply(_status, axis=1)

    return merged[cols]
