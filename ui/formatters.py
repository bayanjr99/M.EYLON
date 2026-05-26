"""פורמטרים מרכזיים לתצוגת מספרים במערכת.

עקרון: רק תצוגה — לא לשנות ערכים מקוריים. כל פונקציה מקבלת number/None/str
ומחזירה str מוכן להצגה. ערכים לא חוקיים מוחזרים כמו שהם (אם בכלל).

מטרת המודול: פורמט אחיד בכל המערכת — פסיקים לאלפים, ₪ לפני סכומים,
% אחרי אחוזים, סימן מינוס לפני שלילי (לא בסוגריים).
"""
from __future__ import annotations

import math


CURRENCY = "₪"
EMPTY = "—"   # placeholder לערך ריק/None
NAN_OR_NONE_TYPES = (type(None),)


def _is_blank(value) -> bool:
    """True אם הערך באמת ריק (None, NaN, מחרוזת ריקה)."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _to_float(value) -> float | None:
    """ממיר מספר בכל פורמט ל-float. מחזיר None אם לא מספרי."""
    if _is_blank(value):
        return None
    try:
        # אם הגיע כבר float/int
        return float(value)
    except (TypeError, ValueError):
        # אם הגיע מחרוזת עם פסיקים/₪/% — ננקה
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace(CURRENCY, "") \
                            .replace("%", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


# ── Public API ──────────────────────────────────────────────

def format_number(value, blank: str = EMPTY) -> str:
    """1000 → '1,000', 1500000 → '1,500,000'.

    Args:
        value: כל מספר או דבר שניתן להמיר ל-float.
        blank: מה להחזיר לערך ריק (ברירת מחדל: '—').
    """
    f = _to_float(value)
    if f is None:
        return blank
    return f"{f:,.0f}"


def format_currency(value, blank: str = EMPTY,
                     symbol: str = CURRENCY) -> str:
    """1000 → '₪1,000', -25000 → '-₪25,000'.

    שלילי: סימן מינוס לפני המטבע, אחיד בכל המערכת.
    """
    f = _to_float(value)
    if f is None:
        return blank
    if f < 0:
        return f"-{symbol}{abs(f):,.0f}"
    return f"{symbol}{f:,.0f}"


def format_decimal(value, decimals: int = 2, blank: str = EMPTY) -> str:
    """12500.756 → '12,500.76' (2 ספרות אחרי הנקודה כברירת מחדל)."""
    f = _to_float(value)
    if f is None:
        return blank
    return f"{f:,.{decimals}f}"


def format_percent(value, decimals: int = 1, blank: str = EMPTY,
                    already_pct: bool = False) -> str:
    """0.253 → '25.3%'. אם already_pct=True: 25.3 → '25.3%' (לא מכפיל ב-100).

    Args:
        already_pct: True אם הערך כבר באחוזים (לא בין 0-1).
    """
    f = _to_float(value)
    if f is None:
        return blank
    if not already_pct:
        f = f * 100
    return f"{f:,.{decimals}f}%"


# ── Convenience helpers ─────────────────────────────────────

def format_currency_with_decimals(value, decimals: int = 2,
                                    blank: str = EMPTY) -> str:
    """₪ עם ספרות עשרוניות. שימושי למחיר לליטר וכו'. 6.94 → '₪6.94'."""
    f = _to_float(value)
    if f is None:
        return blank
    if f < 0:
        return f"-{CURRENCY}{abs(f):,.{decimals}f}"
    return f"{CURRENCY}{f:,.{decimals}f}"


def format_liters(value, blank: str = EMPTY) -> str:
    """ליטרים עם פסיקים: 12500 → '12,500 ל''."""
    f = _to_float(value)
    if f is None:
        return blank
    return f"{f:,.0f} ל'"


def format_hours(value, decimals: int = 1, blank: str = EMPTY) -> str:
    """שעות עם פסיקים: 1500.5 → '1,500.5 ש''."""
    f = _to_float(value)
    if f is None:
        return blank
    return f"{f:,.{decimals}f} ש'"


# ── Date / value cleanup helpers ────────────────────────────

def format_date(value, blank: str = EMPTY) -> str:
    """Datetime / Timestamp / 'YYYY-MM-DD' / '2026-01-31 00:00:00' → '31/01/2026'."""
    import pandas as pd
    if value is None:
        return blank
    try:
        if pd.isna(value):
            return blank
    except (TypeError, ValueError):
        pass
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if ts is None or pd.isna(ts):
            return blank
        return ts.strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def format_month(value, blank: str = EMPTY) -> str:
    """Month label MM-YYYY: handles '2026-01', '01-2026', or datetime → '01-2026'."""
    import pandas as pd
    if value is None:
        return blank
    try:
        if pd.isna(value):
            return blank
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return blank
    # Already in MM-YYYY format
    if len(s) == 7 and s[2] == "-" and s[:2].isdigit() and s[3:].isdigit():
        return s
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if ts is None or pd.isna(ts):
            return s
        return ts.strftime("%m-%Y")
    except Exception:
        return s


def clean_value(value, blank: str = EMPTY) -> str:
    """ערך תאי תצוגה: None/NaN/'nan'/'' → '—' (או blank שניתן)."""
    import pandas as pd
    if value is None:
        return blank
    try:
        if pd.isna(value):
            return blank
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "nat", "none", "null"):
        return blank
    return s


def clean_dataframe_for_display(df, date_cols=None, month_cols=None,
                                  blank: str = EMPTY):
    """מנקה DataFrame לתצוגה: תאריכים → DD/MM/YYYY, NaN → '—'.

    - עמודות שמוחזקות numeric נשארות numeric (פורמט הפסיקים בא דרך column_config).
    - עמודות אובייקט/מחרוזת עם NaN/None מקבלות placeholder.
    - עמודות בשם 'תאריך' / 'date' מקבלות פורמט DD/MM/YYYY.
    - עמודות בשם 'חודש' / 'month' / 'month_label' מקבלות פורמט MM-YYYY.

    Args:
        df: DataFrame להצגה.
        date_cols: רשימת שמות עמודות לפורמט תאריך (אוטו אם None).
        month_cols: רשימת שמות עמודות חודש (אוטו אם None).
        blank: ערך placeholder ל-NaN/ריק.

    Returns:
        DataFrame חדש מוכן לתצוגה (לא משנה את המקורי).
    """
    import pandas as pd
    if df is None or df.empty:
        return df

    out = df.copy()

    # זיהוי אוטומטי של עמודות תאריך/חודש לפי שם
    if date_cols is None:
        date_cols = [c for c in out.columns
                      if str(c).strip() in ("תאריך", "date", "תאריך אסמכתא",
                                              "תאריך ערך", "תאריך התחלה",
                                              "תאריך סיום", "תאריך טיפול",
                                              "תאריך ייבוא")]
    if month_cols is None:
        month_cols = [c for c in out.columns
                       if str(c).strip() in ("חודש", "month", "month_label")]

    # פורמט תאריכים
    for c in date_cols:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: format_date(v, blank=blank))

    # פורמט חודש
    for c in month_cols:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: format_month(v, blank=blank))

    # נקה NaN/None בעמודות לא-numeric
    for c in out.columns:
        if c in date_cols or c in month_cols:
            continue
        # עמודה numeric → נשאיר כפי שהיא (column_config יטפל)
        if pd.api.types.is_numeric_dtype(out[c]):
            continue
        # עמודת object/string — נחליף NaN ל-blank
        out[c] = out[c].apply(lambda v: clean_value(v, blank=blank))

    return out


def display_dataframe(df, **kwargs):
    """st.dataframe wrapper שמחיל קלינ-אפ + column_config אוטומטית.

    שימוש:
        from ui.formatters import display_dataframe
        display_dataframe(df, use_container_width=True, hide_index=True)

    מה הוא עושה:
        1. clean_dataframe_for_display → תאריכים נקיים, NaN → '—'
        2. column_config מ-COMMON_NUMBER_FORMATS → מספרים עם פסיקים

    Args שעוברים כמו שהם ל-st.dataframe.
    """
    import streamlit as st
    cleaned = clean_dataframe_for_display(df)
    kwargs.setdefault("use_container_width", True)
    kwargs.setdefault("hide_index", True)
    if "column_config" not in kwargs and cleaned is not None and not cleaned.empty:
        kwargs["column_config"] = build_column_config(cleaned.columns)
    return st.dataframe(cleaned, **kwargs)


# ── Streamlit column_config helpers ─────────────────────────

# מילון מרכזי של פורמטים לעמודות נפוצות (לפי שם עמודה בעברית).
# שימוש: הגדר את column_config של st.dataframe לפי המילון.
COMMON_NUMBER_FORMATS: dict[str, str] = {
    # סכומי כסף
    "סכום":         "₪%d",
    "סכום (₪)":     "₪%d",
    "סה\"כ":        "₪%d",
    "סה\"כ (₪)":    "₪%d",
    "חובה":         "₪%d",
    "זכות":         "₪%d",
    "נטו":          "₪%d",
    "נטו (₪)":      "₪%d",
    "יתרה":         "₪%d",
    "הכנסות":       "₪%d",
    "הוצאות":       "₪%d",
    "רווח":         "₪%d",
    "עלות":         "₪%d",
    "מחיר":         "₪%d",
    "מחיר (₪)":     "₪%d",
    "תקציב":        "₪%d",
    "בפועל":        "₪%d",
    "עלות משוערת":  "₪%d",
    "עלות משוערת (₪)": "₪%d",
    "סה\"כ ₪":      "₪%d",
    "נזק (₪)":      "₪%d",
    "בזבוז משוער (₪)": "₪%d",
    "השפעה כספית": "₪%d",

    # מספרים רגילים
    "תנועות":       "%d",
    "כפילויות":     "%d",
    "כמות":         "%d",
    "שורות":        "%d",
    "מספר חשבוניות": "%d",
    "ימי עבודה":    "%d",
    "ימי":          "%d",
    "ימים":         "%d",
    "חשבוניות":     "%d",
    "ספקים":        "%d",
    "תדלוקים":      "%d",
    "תנועות נטענו": "%d",

    # ליטרים / שעות
    "ליטרים":         "%d",
    "סה\"כ ליטרים":   "%d",
    "ליטרים (ל')":   "%d",
    "ל'":            "%.1f",
    "סה\"כ שעות":     "%.1f",
    "שעות":          "%.1f",
    "שעות מנוע":     "%.1f",
    "שעות עבודה":    "%.1f",
    "ל'/ש' בפועל":   "%.1f",
    "ל'/ש' מותר":    "%.1f",
    "תקן עליון":     "%.1f",
    "תקן תחתון":     "%.1f",
    "תקן ת'":        "%.1f",
    "תקן ע'":        "%.1f",
    "חריגה (ל')":    "%d",
    "₪/ל'":          "₪%.2f",
}


def build_column_config(df_columns) -> dict:
    """בונה dict של column_config ל-st.dataframe לפי שמות העמודות.

    מחזיר רק עמודות שמופיעות גם ב-df וגם ב-COMMON_NUMBER_FORMATS.
    שימוש:
        st.dataframe(df, column_config=build_column_config(df.columns), ...)
    """
    import streamlit as st  # lazy import
    cfg: dict = {}
    for col in df_columns:
        fmt = COMMON_NUMBER_FORMATS.get(str(col))
        if fmt:
            cfg[col] = st.column_config.NumberColumn(label=col, format=fmt)
        elif "%" in str(col):
            # עמודת אחוז גנרית
            cfg[col] = st.column_config.NumberColumn(label=col, format="%.1f%%")
    return cfg


# ── Plotly tickformat presets ───────────────────────────────
PLOTLY_FORMAT_INT = ",.0f"
PLOTLY_FORMAT_DECIMAL = ",.2f"
PLOTLY_HOVER_CURRENCY = f"{CURRENCY}%{{y:,.0f}}"
