"""חישוב delta של שעות מנוע מקריאות מצטברות.

בעיה: עמודת engine_hours בקובץ המקור היא קריאת מונה מצטברת
(לדוגמה: 8093, 8105, 8120 — כלי שעבד 12 ואז 15 שעות).
אם רוצים לחשב צריכה ל'/שעה מדויקת, צריך delta בין קריאות סמוכות.

לוגיקה:
    לכל כלי (license_num):
        - מיין לפי date
        - לכל שורה (חוץ מהראשונה): delta = curr.engine_hours - prev.engine_hours
        - אם delta > 0 → ok
        - אם delta < 0 → reset_or_error (מונה הוחלף או טעות)
        - אם delta == 0 → zero_work (לא עבד בין תדלוקים)
        - אם delta > 500 → gap_too_large (חודש ויותר בלי תדלוק או טעות)

פלט DataFrame עם:
    delta_engine_hours, hours_quality, hours_quality_note, lph_calculated

API:
    compute_delta(usage_df) → DataFrame עם 4 עמודות חדשות
    summarize_quality(usage_df) → dict עם ספירות לכל סטטוס
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ── סטטוסי איכות ────────────────────────────────────────────
Q_OK = "ok"                  # delta חיובי וסביר
Q_ZERO = "zero_work"         # delta = 0 (לא עבד)
Q_NEGATIVE = "negative"      # delta שלילי (reset או טעות)
Q_GAP_LARGE = "gap_too_large"  # delta > MAX_REASONABLE (גדול מדי)
Q_FIRST = "first_reading"    # שורה ראשונה לכלי (אין delta)
Q_NO_HOURS = "no_engine_hours"  # אין קריאת מונה בכלל

# סף גסות
MAX_REASONABLE_DELTA = 500.0   # שעות עבודה בין תדלוקים סמוכים. מעל זה - חשוד.
MIN_REASONABLE_DELTA = 0.1     # אם 0 → zero_work, אם 0.0-0.1 → ייתכן טעות

# סף לזיהוי lph חריג
MAX_REASONABLE_LPH = 30.0   # ל'/שעה - גבול עליון לכלים כבדים
MIN_REASONABLE_LPH = 1.0    # ל'/שעה - גבול תחתון


# ── חישוב delta ─────────────────────────────────────────────
def compute_delta(usage_df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר DataFrame עם 4 עמודות חדשות לכל שורה.

    Required columns: date, license_num, engine_hours, liters
    Output adds: delta_engine_hours, hours_quality, hours_quality_note,
                 lph_calculated
    """
    if usage_df is None or usage_df.empty:
        out = usage_df.copy() if usage_df is not None else pd.DataFrame()
        for c in ("delta_engine_hours", "hours_quality",
                  "hours_quality_note", "lph_calculated"):
            out[c] = None
        return out

    df = usage_df.copy()
    # ודא טיפוסי עמודות
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["engine_hours"] = pd.to_numeric(df.get("engine_hours"), errors="coerce")
    df["liters"] = pd.to_numeric(df.get("liters"), errors="coerce")
    df["license_num"] = df.get("license_num").astype(str).str.strip()

    # סדר לפי כלי + תאריך
    df = df.sort_values(["license_num", "date"]).reset_index(drop=True)

    # חישוב delta בתוך כל קבוצה
    df["__prev_eh"] = df.groupby("license_num")["engine_hours"].shift(1)
    df["delta_engine_hours"] = df["engine_hours"] - df["__prev_eh"]

    # אבחון איכות
    def _classify(row) -> tuple[str, str]:
        eh = row["engine_hours"]
        delta = row["delta_engine_hours"]
        prev = row["__prev_eh"]

        # אין engine_hours בכלל
        if pd.isna(eh):
            return Q_NO_HOURS, "אין קריאת מונה בשורה זו"

        # שורה ראשונה לכלי (אין prev)
        if pd.isna(prev):
            return Q_FIRST, "שורה ראשונה לכלי - אין delta"

        if pd.isna(delta):
            return Q_NO_HOURS, "delta לא חושב"

        # delta שלילי - מונה הוחלף / טעות
        if delta < 0:
            return Q_NEGATIVE, (f"delta שלילי ({delta:.0f} שעות) - "
                                 f"מונה הוחלף או טעות בקריאה")

        # delta = 0
        if delta < MIN_REASONABLE_DELTA:
            return Q_ZERO, "delta = 0 - הכלי לא עבד בין תדלוקים"

        # delta גדול מדי
        if delta > MAX_REASONABLE_DELTA:
            return Q_GAP_LARGE, (f"delta = {delta:.0f} שעות - גדול מדי. "
                                  f"כנראה פער זמן ארוך או טעות.")

        return Q_OK, ""

    quality = df.apply(_classify, axis=1)
    df["hours_quality"] = [q[0] for q in quality]
    df["hours_quality_note"] = [q[1] for q in quality]

    # חישוב lph רק כש-delta תקין
    def _calc_lph(row) -> float | None:
        if row["hours_quality"] != Q_OK:
            return None
        liters = row["liters"]
        delta = row["delta_engine_hours"]
        if pd.isna(liters) or pd.isna(delta) or delta <= 0:
            return None
        lph = liters / delta
        return round(lph, 2)

    df["lph_calculated"] = df.apply(_calc_lph, axis=1)

    # ניקוי עמודת עזר
    df = df.drop(columns=["__prev_eh"])

    return df


def summarize_quality(usage_with_delta: pd.DataFrame) -> dict:
    """סיכום ספירות לפי סטטוס איכות. מחזיר dict."""
    if usage_with_delta.empty or "hours_quality" not in usage_with_delta.columns:
        return {"total": 0}
    counts = usage_with_delta["hours_quality"].value_counts().to_dict()
    return {
        "total": int(len(usage_with_delta)),
        "ok": int(counts.get(Q_OK, 0)),
        "zero_work": int(counts.get(Q_ZERO, 0)),
        "negative": int(counts.get(Q_NEGATIVE, 0)),
        "gap_too_large": int(counts.get(Q_GAP_LARGE, 0)),
        "first_reading": int(counts.get(Q_FIRST, 0)),
        "no_engine_hours": int(counts.get(Q_NO_HOURS, 0)),
    }


def per_tool_lph(usage_with_delta: pd.DataFrame) -> pd.DataFrame:
    """ממוצעי lph לכל כלי - רק על שורות תקינות (hours_quality = ok)."""
    if usage_with_delta.empty or "lph_calculated" not in usage_with_delta.columns:
        return pd.DataFrame(columns=["license_num", "tool_name",
                                      "n_fuelings_ok", "total_liters_ok",
                                      "total_engine_delta", "lph_avg",
                                      "lph_min", "lph_max", "is_outlier"])

    ok = usage_with_delta[usage_with_delta["hours_quality"] == Q_OK].copy()
    if ok.empty:
        return pd.DataFrame(columns=["license_num", "tool_name",
                                      "n_fuelings_ok", "total_liters_ok",
                                      "total_engine_delta", "lph_avg",
                                      "lph_min", "lph_max", "is_outlier"])

    agg = ok.groupby("license_num").agg(
        tool_name=("tool_name", lambda s: s.dropna().mode().iloc[0]
                       if not s.dropna().mode().empty else ""),
        n_fuelings_ok=("lph_calculated", "size"),
        total_liters_ok=("liters", "sum"),
        total_engine_delta=("delta_engine_hours", "sum"),
        lph_min=("lph_calculated", "min"),
        lph_max=("lph_calculated", "max"),
    ).reset_index()
    # lph_avg = total_liters_ok / total_engine_delta (משוקלל לפי גודל)
    agg["lph_avg"] = (agg["total_liters_ok"] / agg["total_engine_delta"]).round(2)
    agg["is_outlier"] = agg["lph_avg"].apply(
        lambda v: bool(pd.notna(v) and
                       (v > MAX_REASONABLE_LPH or v < MIN_REASONABLE_LPH))
    )
    agg["total_liters_ok"] = agg["total_liters_ok"].round(0)
    agg["total_engine_delta"] = agg["total_engine_delta"].round(1)
    agg["lph_min"] = agg["lph_min"].round(2)
    agg["lph_max"] = agg["lph_max"].round(2)
    return agg.sort_values("total_liters_ok", ascending=False).reset_index(drop=True)
