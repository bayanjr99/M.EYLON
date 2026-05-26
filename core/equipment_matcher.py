"""חיבור תנועות דלק/שעות/אחזקה לכלים ב-tools_registry.

לוגיקת התאמה (סדר עדיפויות):
    1. license_num exact (normalized)
    2. internal_num exact
    3. tool_name normalized exact
    4. license extracted from description (regex + normalized)
    5. partial: tool_name appears as substring in description
    6. unmatched → להעביר לחריגות

סיווג סופי לאחר match (`classify_transaction`):
    - matched_to_tool          — נמצא ב-tools_registry
    - missing_from_registry    — חולץ רישוי אבל לא ב-registry
    - bulk_delivery            — מסירה לצובר (לפי ספק)
    - unmatched_no_clue        — אין שום מידע לזהות

בדיקת validation (אחרי match):
    - סוג דלק תנועה vs fuel_type של הכלי
    - סטטוס פעיל
    - כלי קיים ב-registry
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# regex לזיהוי מספרי רישוי בטקסט חופשי
# פורמטים נפוצים: 168792, 426-84-302, 510-66-104, 638-12-903
_LICENSE_DASH_RE = re.compile(r"\b(\d{1,3})-(\d{1,3})-(\d{1,3})\b")
_LICENSE_DIGITS_RE = re.compile(r"\b(\d{5,8})\b")
_NUMSEP_RE = re.compile(r"[\s\-.,_/]")


def normalize_license_num(value: Any) -> int | None:
    """מנרמל מספר רישוי לפורמט canonical (int יחיד).

    מטפל ב:
        '510-66-104'   → 51066104
        '510 66 104'   → 51066104
        '510.66.104'   → 51066104
        ' 168792 '     → 168792
        '168792.0'     → 168792
        '0168792'      → 168792 (מסיר אפסים מובילים)
        168792.0       → 168792 (float)
        168792         → 168792 (int passthrough)
        None / NaN / '' / '0' → None

    Returns:
        int או None אם לא ניתן לחלץ ערך תקין.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            if value != value:  # NaN
                return None
            try:
                n = int(value)
            except (OverflowError, ValueError):
                return None
        else:
            n = value
        return n if n > 0 else None
    s = str(value).strip()
    if not s:
        return None
    # מקרה (a): float-string ("168792.0") — סינגלי "." בלי separators אחרים
    # → לפרסר כ-float ולחתוך את החלק העשרוני (מטפל גם ב-"168792.0", "168792.5" → 168792)
    if "." in s and not any(c in s for c in "-, _/"):
        try:
            f = float(s)
            if f > 0:
                return int(f)
        except (ValueError, TypeError):
            pass
    # מקרה (b): מספר עם separators (מקפים/נקודות/רווחים בין חלקים) — נחבר את כולם
    # "510-66-104" → "51066104" ; "510.66.104" → "51066104"
    s_clean = _NUMSEP_RE.sub("", s)
    if not s_clean or not s_clean.isdigit():
        return None
    try:
        n = int(s_clean)
    except ValueError:
        return None
    return n if n > 0 else None


def extract_license_from_text(text: str) -> int | None:
    """מנסה לחלץ מספר רישוי/כלי מטקסט חופשי.

    דוגמאות שאמורות לעבוד:
        "טעינת רכב חשמלי מס' 510-66-104" → 51066104
        "שופל קטרפילר 168792" → 168792
        "פורד אדי 426-84-302" → 4268430
    """
    if not isinstance(text, str) or not text.strip():
        return None
    # קודם נסה עם מקפים (מדויק יותר ללוחיות רכב)
    m = _LICENSE_DASH_RE.search(text)
    if m:
        normalized = normalize_license_num(m.group(0))
        if normalized:
            return normalized
    # אחר כך נסה רצף של 5-8 ספרות
    for m in _LICENSE_DIGITS_RE.finditer(text):
        n = normalize_license_num(m.group(1))
        if n:
            return n
    return None


# מילות מפתח לזיהוי ספקי דלק "צובר" — חשבוניות מהם בדרך כלל למסירה
# לפרויקט שלם (לא לרכב ספציפי). מטופל ע"י substring match כי שמות הספקים
# בנהלת חשבונות מגיעים עם וריאציות (בע"מ, שותפויות, נקודות, וכו').
BULK_FUEL_SUPPLIER_KEYWORDS = [
    "קפיטל אנרג",       # קפיטל אנרג'י
    "ג'אן",                # נ. ג'אן (substring יתפוס גם "נ. ג'אן בע\"מ")
    "וואן דלקים",
    "פז דלקים",
    "פז חברת",
    "סונול",
    "דור אלון",
    "דלק מוטורס",
    "ש.מ.ר. דלק",
]


def is_bulk_fuel_supplier(supplier: Any) -> bool:
    """True אם ספק מזוהה כספק דלק לצובר (לא לרכב ספציפי)."""
    if not supplier or pd.isna(supplier):
        return False
    s = str(supplier).strip()
    return any(kw in s for kw in BULK_FUEL_SUPPLIER_KEYWORDS)


# סטטוסי סיווג סופי לתנועת דלק
CLASS_MATCHED = "matched_to_tool"
CLASS_MISSING = "missing_from_registry"
CLASS_BULK = "bulk_delivery"
CLASS_UNMATCHED = "unmatched_no_clue"

CLASS_LABEL_HE = {
    CLASS_MATCHED:   "✓ הותאם לכלי",
    CLASS_MISSING:   "⚠ כלי חסר ברשימה",
    CLASS_BULK:      "📦 מסירה לצובר",
    CLASS_UNMATCHED: "❓ ללא זיהוי",
}


def classify_transaction(row: pd.Series) -> str:
    """מסווג תנועת דלק לאחת מ-4 קטגוריות.

    - matched_to_tool: matched_by != "unmatched"
    - missing_from_registry: יש extracted_license אבל אין match
    - bulk_delivery: ספק מזוהה כצובר ואין license מחולץ
    - unmatched_no_clue: שום אינדיקציה
    """
    matched_by = row.get("matched_by", "")
    if matched_by and matched_by != "unmatched":
        return CLASS_MATCHED
    if pd.notna(row.get("extracted_license")) and row.get("extracted_license"):
        return CLASS_MISSING
    if is_bulk_fuel_supplier(row.get("supplier", "")):
        return CLASS_BULK
    return CLASS_UNMATCHED


def _normalize_hebrew(s: str) -> str:
    """נרמול בסיסי לטקסט עברי - הסרת רווחים כפולים, lowercase."""
    if not isinstance(s, str):
        return ""
    return " ".join(s.lower().split())


UNMATCHED = {
    "equipment_id": None,
    "matched_license_num": None,
    "matched_tool_name": None,
    "matched_by": "unmatched",
    "match_confidence": "low",
    "match_note": "לא נמצאה התאמה לכלי",
}


def match_to_equipment(license_num: Any, tool_name: str = "",
                        description: str = "", internal_num: str = "",
                        equipment_df: pd.DataFrame = None) -> dict:
    """מחזיר dict עם equipment_id + matched_by + match_confidence + match_note.

    לפי סדר עדיפויות. UNMATCHED אם אין התאמה ברורה.
    """
    if equipment_df is None or equipment_df.empty:
        return dict(UNMATCHED, match_note="אין tools_registry טעון")

    # 1. license_num exact (normalized)
    lic = normalize_license_num(license_num)
    if lic is not None:
        # ננסה גם בלי וגם עם נירמול בעמודת ה-registry
        # (אם ה-registry שמור עם dashes, נצטרך לנרמל גם אותו)
        hit = equipment_df[equipment_df["license_num"] == lic]
        if hit.empty and "license_num" in equipment_df.columns:
            # fallback: נירמול גם בצד ה-registry
            reg_normalized = equipment_df["license_num"].apply(normalize_license_num)
            hit = equipment_df[reg_normalized == lic]
        if not hit.empty:
            row = hit.iloc[0]
            return {
                "equipment_id": int(row.get("id", lic)),
                "matched_license_num": lic,
                "matched_tool_name": str(row.get("tool_name", "")),
                "matched_by": "license_num",
                "match_confidence": "high",
                "match_note": f"exact license {lic}",
            }

    # 2. internal_num exact
    if internal_num and str(internal_num).strip() and "internal_num" in equipment_df.columns:
        inum = str(internal_num).strip()
        hit = equipment_df[equipment_df["internal_num"].fillna("").astype(str) == inum]
        if not hit.empty:
            row = hit.iloc[0]
            return {
                "equipment_id": int(row.get("id", row.get("license_num", 0))),
                "matched_license_num": int(row["license_num"]) if pd.notna(row.get("license_num")) else None,
                "matched_tool_name": str(row.get("tool_name", "")),
                "matched_by": "internal_num",
                "match_confidence": "high",
                "match_note": f"internal_num {inum}",
            }

    # 3. tool_name normalized exact
    if tool_name and str(tool_name).strip():
        tname_n = _normalize_hebrew(str(tool_name))
        if tname_n:
            for _, eq in equipment_df.iterrows():
                eq_name_n = _normalize_hebrew(str(eq.get("tool_name", "")))
                if eq_name_n and eq_name_n == tname_n:
                    return {
                        "equipment_id": int(eq.get("id", eq.get("license_num", 0))),
                        "matched_license_num": int(eq["license_num"]) if pd.notna(eq.get("license_num")) else None,
                        "matched_tool_name": str(eq.get("tool_name", "")),
                        "matched_by": "tool_name",
                        "match_confidence": "high",
                        "match_note": f"שם זהה: {tool_name}",
                    }

    # 4. license extracted from description (with normalization on both sides)
    if description and str(description).strip():
        extracted_lic = extract_license_from_text(str(description))
        if extracted_lic:
            hit = equipment_df[equipment_df["license_num"] == extracted_lic]
            if hit.empty and "license_num" in equipment_df.columns:
                reg_normalized = equipment_df["license_num"].apply(normalize_license_num)
                hit = equipment_df[reg_normalized == extracted_lic]
            if not hit.empty:
                row = hit.iloc[0]
                return {
                    "equipment_id": int(row.get("id", extracted_lic)),
                    "matched_license_num": extracted_lic,
                    "matched_tool_name": str(row.get("tool_name", "")),
                    "matched_by": "license_in_description",
                    "match_confidence": "medium",
                    "match_note": f"חולץ מהפרטים: {extracted_lic}",
                }

    # 5. partial: tool_name appears as substring in description
    if description and len(str(description)) > 5:
        desc_n = _normalize_hebrew(str(description))
        for _, eq in equipment_df.iterrows():
            eq_name = str(eq.get("tool_name", "")).strip()
            if len(eq_name) >= 4:
                eq_name_n = _normalize_hebrew(eq_name)
                if eq_name_n and eq_name_n in desc_n:
                    return {
                        "equipment_id": int(eq.get("id", eq.get("license_num", 0))),
                        "matched_license_num": int(eq["license_num"]) if pd.notna(eq.get("license_num")) else None,
                        "matched_tool_name": eq_name,
                        "matched_by": "partial_tool_name",
                        "match_confidence": "low",
                        "match_note": f"חלקי: '{eq_name}' בפרטים",
                    }

    # 6. unmatched
    return dict(UNMATCHED)


# בדיקות validation בין סוג דלק לסוג כלי
def validate_fuel_for_equipment(transaction_fuel_type: str,
                                  equipment_row: pd.Series | None) -> dict:
    """מחזיר dict עם status + note. status: ok / warning / error."""
    if equipment_row is None or (hasattr(equipment_row, "empty") and equipment_row.empty):
        return {"validation_status": "warning",
                "validation_note": "לא נמצאה התאמה לכלי"}

    eq_fuel = str(equipment_row.get("fuel_type") or "").strip()
    eq_status = str(equipment_row.get("status") or "").strip()
    eq_group = str(equipment_row.get("equipment_group") or "").strip()
    tx_fuel = (transaction_fuel_type or "").strip()

    # סטטוס לא פעיל
    if eq_status == "לא פעיל":
        return {"validation_status": "warning",
                "validation_note": "כלי לא פעיל מקבל דלק"}

    # אם fuel_type של הכלי לא הוגדר - לא בודקים mismatch
    if not eq_fuel or eq_fuel == "לא רלוונטי":
        return {"validation_status": "ok", "validation_note": ""}

    # אם סוג הדלק בתנועה לא הוגדר - לא בודקים
    if not tx_fuel or tx_fuel == "לא מסווג":
        return {"validation_status": "warning",
                "validation_note": "סוג הדלק בתנועה לא ידוע"}

    if eq_fuel == tx_fuel:
        return {"validation_status": "ok", "validation_note": ""}

    # אי-התאמות חמורות
    if eq_fuel == "חשמל" and tx_fuel in ("סולר", "בנזין"):
        return {"validation_status": "error",
                "validation_note": f"דלק '{tx_fuel}' לרכב חשמלי"}
    if tx_fuel == "חשמל" and eq_fuel in ("סולר", "בנזין"):
        return {"validation_status": "error",
                "validation_note": "טעינת חשמל לכלי דלק"}
    if eq_fuel == "סולר" and tx_fuel == "בנזין":
        return {"validation_status": "error",
                "validation_note": "בנזין לכלי סולר"}
    if eq_fuel == "בנזין" and tx_fuel == "סולר":
        return {"validation_status": "error",
                "validation_note": "סולר לכלי בנזין"}

    return {"validation_status": "warning",
            "validation_note": f"דלק '{tx_fuel}' לכלי '{eq_fuel}'"}


def enrich_fuel_transactions(df: pd.DataFrame,
                              equipment_df: pd.DataFrame,
                              license_col: str = "license_num",
                              tool_name_col: str = "tool_name",
                              description_col: str = "description",
                              fuel_type_col: str = "fuel_type") -> pd.DataFrame:
    """מוסיף עמודות match + validation + equipment metadata.

    Returns DataFrame עם 11 שדות חדשים:
      equipment_id, matched_license_num, matched_tool_name,
      matched_by, match_confidence, match_note,
      validation_status, validation_note,
      equipment_group, fuel_type_of_equipment, fuel_type_actual,
      extracted_license (אם חולץ מהפרטים גם בלי התאמה).
    """
    if df.empty:
        return df.assign(
            equipment_id=None, matched_license_num=None, matched_tool_name="",
            matched_by="", match_confidence="", match_note="",
            validation_status="", validation_note="",
            equipment_group="", fuel_type_of_equipment="",
            fuel_type_actual="", extracted_license=None,
        )

    eq_indexed = equipment_df.set_index("license_num", drop=False) \
        if not equipment_df.empty and "license_num" in equipment_df.columns \
        else pd.DataFrame()

    results = []
    for _, row in df.iterrows():
        match = match_to_equipment(
            license_num=row.get(license_col),
            tool_name=row.get(tool_name_col, ""),
            description=row.get(description_col, ""),
            equipment_df=equipment_df,
        )
        eq_row = None
        if match["matched_license_num"] is not None and not eq_indexed.empty:
            try:
                eq_row = eq_indexed.loc[match["matched_license_num"]]
                if isinstance(eq_row, pd.DataFrame):
                    eq_row = eq_row.iloc[0]
            except KeyError:
                eq_row = None
        validation = validate_fuel_for_equipment(
            row.get(fuel_type_col, ""), eq_row,
        )
        match.update(validation)

        # 3 שדות מטא-נתונים נוספים (מהכלי + מהתנועה)
        if eq_row is not None and not (hasattr(eq_row, "empty") and eq_row.empty):
            match["equipment_group"] = str(eq_row.get("equipment_group") or "")
            match["fuel_type_of_equipment"] = str(eq_row.get("fuel_type") or "")
        else:
            match["equipment_group"] = ""
            match["fuel_type_of_equipment"] = ""
        match["fuel_type_actual"] = str(row.get(fuel_type_col) or "")

        # extracted_license: גם אם לא הצליח להתאים, להראות מה חולץ
        ext = extract_license_from_text(str(row.get(description_col) or ""))
        match["extracted_license"] = ext

        results.append(match)

    enrich_df = pd.DataFrame(results)
    out = df.copy().reset_index(drop=True)
    for col in enrich_df.columns:
        out[col] = enrich_df[col].values

    # סיווג סופי ל-4 קטגוריות
    out["classification"] = out.apply(classify_transaction, axis=1)
    out["classification_label"] = out["classification"].map(CLASS_LABEL_HE).fillna("")
    return out


def unmatched_vehicle_candidates(enriched_df: pd.DataFrame) -> pd.DataFrame:
    """מאתר רכבים שמופיעים בתיאורים אך לא קיימים ב-tools_registry.

    שימושי: המשתמש יכול לראות בלחיצה אחת אילו רכבים חסרים, ולהוסיף אותם.

    Returns DataFrame עם: extracted_license, sample_description, n_tx, total_cost.
    """
    cols = ["extracted_license", "sample_description", "n_tx", "total_cost"]
    if enriched_df.empty:
        return pd.DataFrame(columns=cols)
    unmatched = enriched_df[
        (enriched_df["matched_by"] == "unmatched") &
        (enriched_df["extracted_license"].notna())
    ]
    if unmatched.empty:
        return pd.DataFrame(columns=cols)
    g = unmatched.groupby("extracted_license").agg(
        sample_description=("description",
                              lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
        n_tx=("matched_by", "size"),
        total_cost=("total_cost",
                      lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    g["total_cost"] = g["total_cost"].round(0)
    g["extracted_license"] = g["extracted_license"].astype(int)
    return g.sort_values("total_cost", ascending=False)
