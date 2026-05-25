"""סיווג חשבונות חשבשבת לקטגוריות עסקיות.

טוען את data/category_mapping.xlsx ומחזיר קטגוריה לכל חשבון.

סדר ההתאמה:
    1. account_num — exact match לפי מספר חשבון
    2. name_keyword — substring match על account_name, לפי priority
    3. range fallback — לפי מספר חשבון (טווח חשבונאי)
    4. "אחר"

מבנה category_mapping.xlsx:
    priority | account_num | name_keyword | category | subcategory
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "category_mapping.xlsx"


def _classify_by_range(account_num: int) -> tuple[str, str]:
    """סיווג ברירת מחדל לחשבונות שלא במיפוי."""
    if 7430 <= account_num <= 7440:
        return ("הוצאות תפעוליות", "")
    if 7400 <= account_num <= 7499:
        return ("הוצאות פרויקט", "")
    if 7000 <= account_num <= 7399:
        return ("הוצאות שכר/כלליות", "")
    return ("אחר", "")


@lru_cache(maxsize=1)
def load_category_mapping(mapping_path: str = str(DEFAULT_MAPPING_PATH)) -> pd.DataFrame:
    """טוען את קובץ המיפוי. ממוטמן (lru_cache).

    Returns DataFrame עם עמודות: priority, account_num, name_keyword, category, subcategory.
    מסונן ל-rules תקפים (לפחות אחד מ-account_num/name_keyword חייב להיות מלא).
    """
    path = Path(mapping_path)
    cols = ["priority", "account_num", "name_keyword", "category", "subcategory"]
    if not path.exists():
        logger.warning("category_mapping.xlsx not found at %s", path)
        return pd.DataFrame(columns=cols)

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to read category_mapping: %s", e)
        return pd.DataFrame(columns=cols)

    # סכמה לאחור-תאימה - אם אין priority, ברירת מחדל 50
    if "priority" not in df.columns:
        df["priority"] = 50
    if "name_keyword" not in df.columns:
        df["name_keyword"] = ""

    df["account_num"] = pd.to_numeric(df["account_num"], errors="coerce").astype("Int64")
    df["name_keyword"] = df["name_keyword"].fillna("").astype(str).str.strip()
    df["category"] = df["category"].fillna("אחר").astype(str)
    df["subcategory"] = df.get("subcategory", "").fillna("").astype(str)
    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(50).astype(int)

    # סנן rules ריקים
    valid = df[df["account_num"].notna() | (df["name_keyword"] != "")]
    return valid.sort_values("priority").reset_index(drop=True)


def categorize(account_num: int, account_name: str = "") -> tuple[str, str]:
    """מחזיר (category, subcategory) לחשבון נתון.

    סדר: exact account_num → keyword on account_name (לפי priority) → range fallback.
    """
    if account_num is None:
        return ("אחר", "")
    try:
        acct = int(account_num)
    except (TypeError, ValueError):
        return ("אחר", "")

    mapping = load_category_mapping()
    name_l = (account_name or "").lower()

    # שלב 1: exact account_num match
    if not mapping.empty:
        exact = mapping[mapping["account_num"] == acct]
        if not exact.empty:
            r = exact.iloc[0]
            return (r["category"], r["subcategory"])

    # שלב 2: keyword match (כבר ממוין לפי priority)
    if name_l:
        for _, r in mapping[mapping["name_keyword"] != ""].iterrows():
            kw = r["name_keyword"].lower()
            if kw and kw in name_l:
                return (r["category"], r["subcategory"])

    # שלב 3: range fallback
    return _classify_by_range(acct)


# ── Fuel sub-classification (data-driven via fuel_rules.xlsx) ─
FUEL_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "fuel_rules.xlsx"


@lru_cache(maxsize=1)
def load_fuel_rules(path: str = str(FUEL_RULES_PATH)) -> pd.DataFrame:
    """טוען את fuel_rules.xlsx (idempotent + cached).

    סכמה: priority / account_num / description_keyword /
           main_category / sub_category / equipment_group /
           fuel_type / confidence / note.
    """
    p = Path(path)
    cols = ["priority", "account_num", "description_keyword",
            "main_category", "sub_category", "equipment_group",
            "fuel_type", "confidence", "note"]
    if not p.exists():
        logger.info("fuel_rules.xlsx not found, using fallback hardcoded rules")
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_excel(p, engine="openpyxl")
    except Exception as e:
        logger.exception("Failed to load fuel_rules: %s", e)
        return pd.DataFrame(columns=cols)
    df["account_num"] = pd.to_numeric(df["account_num"], errors="coerce").astype("Int64")
    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(50).astype(int)
    df["description_keyword"] = df["description_keyword"].fillna("").astype(str).str.strip()
    for c in ("main_category", "sub_category", "equipment_group",
                "fuel_type", "confidence", "note"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()
    return df.sort_values("priority").reset_index(drop=True)


# Hardcoded fallback - לתאימות לאחור אם fuel_rules.xlsx חסר
_HARDCODED_FUEL_ACCOUNTS = {74327, 74317, 74331}


def _classify_fuel_subcategory(account_num: int | None,
                                description: str) -> tuple[str, str, str, str] | None:
    """Returns (main_category, sub_category, confidence, note) for fuel
    accounts; None if not a fuel account.

    1. מנסה fuel_rules.xlsx (data-driven, ניתן להרחיב בלי קוד)
    2. fallback להגדרות hardcoded לחשבונות 74327 / 74317 / 74331
    """
    if account_num is None:
        return None

    rules = load_fuel_rules()
    if not rules.empty:
        acct_rules = rules[rules["account_num"] == account_num]
        if not acct_rules.empty:
            desc = (description or "").strip()
            for _, r in acct_rules.iterrows():
                kw = r["description_keyword"]
                # ריק = catch-all (תמיד מתאים)
                if not kw or kw.lower() in desc.lower():
                    main = r.get("main_category") or "אחר"
                    sub = r.get("sub_category") or ""
                    conf = r.get("confidence") or "high"
                    note = r.get("note") or "מתוך fuel_rules.xlsx"
                    return (main, sub, conf, note)
            # יש כללים לחשבון אבל אף אחד לא תפס - לא מסווג
            return ("דלק ואנרגיה", "דלק לא מסווג", "low",
                    "חשבון דלק אך אף כלל לא תפס")

    # Fallback hardcoded (אם fuel_rules.xlsx חסר/ריק)
    if account_num not in _HARDCODED_FUEL_ACCOUNTS:
        return None
    if account_num == 74327:
        return ("דלק ואנרגיה", "סולר צמ\"ה", "high", "fallback: חשבון 74327")
    if account_num == 74331:
        return ("אחזקת כלים", "שמנים/אוריאה", "high", "fallback: חשבון 74331")
    # 74317
    desc = (description or "").lower()
    if any(kw in desc for kw in ["טעינת רכב חשמלי", "רכב חשמלי", "אפקון", "תחבורה חשמלית"]):
        return ("דלק ואנרגיה", "טעינת חשמל רכבים", "high", "fallback: חשמלי")
    if "בנזין" in desc:
        return ("דלק ואנרגיה", "בנזין רכבים", "high", "fallback: בנזין")
    if "סולר" in desc:
        return ("דלק ואנרגיה", "סולר רכבים", "high", "fallback: סולר")
    return ("דלק ואנרגיה", "דלק לא מסווג", "low", "fallback: לא זוהה")


# ── Account type detection ────────────────────────────────────
_REVENUE_KEYWORDS = ["הכנסות", "מכירות"]
_EXPENSE_KEYWORDS = ["הוצאות", "הוצאה", "חיוב", "עלות"]


def _detect_account_type(account_num: int | None, account_name: str | None) -> str:
    """Detect account_type by account_num + name.

    Returns: revenue / expense / asset / liability / unknown.
    """
    from core.chashbashevet_loader import INCOME_ACCOUNTS
    name = (account_name or "").strip()

    # Revenue accounts (hard set + name keyword)
    if account_num in INCOME_ACCOUNTS:
        return "revenue"
    if any(kw in name for kw in _REVENUE_KEYWORDS):
        # Income usually starts with "הכנסות". But many expense accounts
        # also contain "הוצאות" — that gets caught below. We do this in order:
        # "הכנסות" check first because if it has both, the income is more
        # specific (e.g., "הכנסות זקופות").
        return "revenue"

    # Expense accounts
    if any(kw in name for kw in _EXPENSE_KEYWORDS):
        return "expense"
    if account_num is not None and 7000 <= account_num <= 9999999999:
        return "expense"
    if account_num is not None and 5000 <= account_num <= 5999:
        return "asset"
    if account_num is not None and 6000 <= account_num <= 6999:
        return "liability"
    return "unknown"


def classify_transaction(account_num: int | None, account_name: str | None,
                          description: str = "", debit: float = 0.0,
                          credit: float = 0.0) -> dict:
    """סיווג מלא של תנועה. מחזיר dict עם 7 שדות לפי המפרט.

    שדות מוחזרים:
        account_type, main_category, sub_category,
        signed_amount, net_amount, is_credit_note,
        classification_confidence, classification_note.

    לוגיקת net_amount:
        revenue: credit - debit  (חיובי = הכנסה אמיתית)
        expense: debit - credit  (חיובי = הוצאה אמיתית)
        unknown: debit - credit  (ברירת מחדל)
    """
    acct_int = None
    if account_num is not None:
        try:
            acct_int = int(account_num)
        except (TypeError, ValueError):
            pass

    debit_f = float(debit or 0)
    credit_f = float(credit or 0)

    # 1. account_type
    account_type = _detect_account_type(acct_int, account_name)

    # 2. main_category + sub_category — try fuel override first
    fuel = _classify_fuel_subcategory(acct_int, description)
    if fuel is not None:
        main_cat, sub_cat, confidence, note = fuel
    else:
        main_cat, sub_cat = categorize(acct_int or 0, account_name or "")
        fallback_cats = {"אחר", "הוצאות תפעוליות", "הוצאות פרויקט",
                          "הוצאות שכר/כלליות"}
        confidence = "low" if main_cat in fallback_cats else "high"
        note = "מתוך מיפוי קטגוריות" if main_cat not in fallback_cats else "ברירת מחדל לפי טווח חשבון"

    # 3. net_amount + signed_amount
    if account_type == "revenue":
        net = credit_f - debit_f
        is_credit_note = debit_f > 0 and credit_f == 0
    elif account_type == "expense":
        net = debit_f - credit_f
        is_credit_note = credit_f > 0 and debit_f == 0
    else:
        net = debit_f - credit_f
        is_credit_note = False

    return {
        "account_type": account_type,
        "main_category": main_cat,
        "sub_category": sub_cat,
        "signed_amount": round(net, 2),
        "net_amount": round(net, 2),
        "is_credit_note": is_credit_note,
        "classification_confidence": confidence,
        "classification_note": note,
    }


def categorize_dataframe(df: pd.DataFrame, account_col: str = "account_num",
                         name_col: str = "account_name") -> pd.DataFrame:
    """מוסיף עמודות category + subcategory ל-DataFrame קיים.

    משתמש ב-categorize() שורה-שורה (יחסית יקר, אבל פשוט וברור).
    לדאטה גדול אפשר לשפר ע"י vectorization של exact-match, אבל לא קריטי כרגע.
    """
    if df.empty or account_col not in df.columns:
        df = df.copy()
        df["category"] = ""
        df["subcategory"] = ""
        return df

    df = df.copy()
    name_series = df[name_col] if name_col in df.columns else pd.Series([""] * len(df), index=df.index)
    results = [
        categorize(row_num, row_name)
        for row_num, row_name in zip(df[account_col], name_series)
    ]
    df["category"] = [c for c, _ in results]
    df["subcategory"] = [s for _, s in results]
    return df


def report_unmapped(df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר דוח חשבונות שלא קיבלו קטגוריה מפורשת.

    כלומר נפלו לטווח (הוצאות תפעוליות / פרויקט / שכר / אחר).
    שימושי כדי לראות מה צריך להוסיף ל-category_mapping.xlsx.
    """
    range_fallback_cats = {"הוצאות תפעוליות", "הוצאות פרויקט",
                           "הוצאות שכר/כלליות", "אחר"}
    if df.empty or "category" not in df.columns:
        return pd.DataFrame(columns=["account_num", "account_name", "category",
                                      "total_amount", "num_transactions"])

    unmapped = df[df["category"].isin(range_fallback_cats)]
    if unmapped.empty:
        return pd.DataFrame(columns=["account_num", "account_name", "category",
                                      "total_amount", "num_transactions"])

    agg = unmapped.groupby(["account_num", "account_name", "category"], dropna=False).agg(
        total_amount=("amount", lambda s: float(s.abs().sum())),
        num_transactions=("amount", "size"),
    ).reset_index().sort_values("total_amount", ascending=False)
    return agg


def save_unmapped_report(df: pd.DataFrame, out_path: str | Path | None = None) -> Path:
    """שומר את דוח הלא-ממופים ל-output/reports/unmapped_accounts.xlsx."""
    if out_path is None:
        out_path = (Path(__file__).resolve().parent.parent /
                    "output" / "reports" / "unmapped_accounts.xlsx")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = report_unmapped(df)
    report.to_excel(out_path, index=False, engine="openpyxl")
    logger.info("Saved unmapped report (%d rows) to %s", len(report), out_path)
    return out_path
