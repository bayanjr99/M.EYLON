"""זיהוי חריגות בנתוני פרויקט - הלב של מערכת הביקורת.

מבצע 5 בדיקות עיקריות:
    1. חריגת צריכת סולר (ליטר/שעה > תקן עליון).
    2. תדלוקים ללא שעות עבודה.
    3. שעות עבודה חריגות (>14 ביום, או שליליות).
    4. חיובים גדולים מאוד (>100,000 ש"ח).
    5. תנועות עם מילות מפתח חשודות.

כל flag נשמר כ-JSON בעמודה anomaly_flags של master.parquet.
"""
from __future__ import annotations

import json
import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ── קבועי ביקורת ──────────────────────────────────────────────
PRICE_PER_LITER_NIS = 7.5         # מחיר ליטר סולר משוער (לחישוב נזק כספי)
SOLAR_DEVIATION_RATIO = 1.15      # > 115% מהתקן העליון = חריגה
LARGE_TRANSACTION_NIS = 100_000   # סף חיוב גדול
MAX_WORK_HOURS_PER_DAY = 14.0     # יותר מזה = חריגה

SUSPICIOUS_KEYWORDS = ["לבטל", "טעות", "תיקון", "החזר", "ביטול"]

# כלי תמיכה שאין להם שעות עבודה רגילות (לא לסמן solar_without_hours)
SUPPORT_TOOL_TYPES = {"גנרטור 100 KVA", "רכב", "טנדר", "גנרטור"}


# עמודות סטנדרטיות לטבלת חריגות מאוחדת
ANOMALIES_COLS = [
    "project_id", "month", "check_type", "severity",
    "entity", "details", "estimated_impact_nis",
]


def detect_solar_excess(
    df_solar_monthly: pd.DataFrame,
    df_hours_monthly: pd.DataFrame,
    tools_registry: pd.DataFrame,
) -> pd.DataFrame:
    """בדיקה 1: חריגת צריכת סולר ביחס לתקן הכלי.

    Args:
        df_solar_monthly: סולר מקובץ ל-(license_num, month, total_liters).
        df_hours_monthly: שעות מקובצות ל-(license_num, month, total_work_hours).
        tools_registry: מתוך data/tools_registry.xlsx (norm_low, norm_high).

    Returns:
        DataFrame עם: license_num, tool_name, month, total_liters,
        total_hours, actual_lph, norm_high, excess_liters,
        damage_estimate_nis, flag_severity ('high'/'medium'/None).
    """
    cols = ["license_num", "tool_name", "month", "total_liters",
            "total_hours", "actual_lph", "norm_high", "excess_liters",
            "damage_estimate_nis", "flag_severity"]
    if df_solar_monthly.empty or df_hours_monthly.empty:
        return pd.DataFrame(columns=cols)

    merged = df_solar_monthly.merge(
        df_hours_monthly[["license_num", "month", "total_work_hours"]],
        on=["license_num", "month"],
        how="left",
    )
    merged = merged.merge(
        tools_registry[["license_num", "norm_high"]],
        on="license_num",
        how="left",
    )

    merged["total_hours"] = merged["total_work_hours"].fillna(0)
    merged["actual_lph"] = merged.apply(
        lambda r: r["total_liters"] / r["total_hours"] if r["total_hours"] > 0 else 0.0,
        axis=1,
    )

    # רק כלים עם תקן ידוע ועם שעות עבודה > 0
    valid = merged[merged["norm_high"].notna() & (merged["total_hours"] > 0)].copy()
    if valid.empty:
        return pd.DataFrame(columns=cols)

    valid["excess_liters"] = (
        (valid["actual_lph"] - valid["norm_high"]) * valid["total_hours"]
    ).clip(lower=0)
    valid["damage_estimate_nis"] = (valid["excess_liters"] * PRICE_PER_LITER_NIS).round(2)

    def _severity(row) -> str | None:
        ratio = row["actual_lph"] / row["norm_high"] if row["norm_high"] else 0
        if ratio > SOLAR_DEVIATION_RATIO * 1.3:
            return "high"
        if ratio > SOLAR_DEVIATION_RATIO:
            return "medium"
        return None

    valid["flag_severity"] = valid.apply(_severity, axis=1)
    flagged = valid[valid["flag_severity"].notna()].copy()
    return flagged[cols].reset_index(drop=True)


def detect_solar_without_hours(
    df_solar_monthly: pd.DataFrame,
    df_hours_monthly: pd.DataFrame,
    tools_registry: pd.DataFrame,
) -> pd.DataFrame:
    """בדיקה 2: כלי שתודלק אך לא דווחו עליו שעות עבודה.

    מתעלם מכלי תמיכה (גנרטור, רכב, טנדר).
    """
    cols = ["license_num", "tool_name", "tool_type", "month",
            "total_liters", "estimated_waste_nis"]
    if df_solar_monthly.empty:
        return pd.DataFrame(columns=cols)

    # שעות עבודה עשויות להיות ריקות לגמרי (למשל חודש עם הזנת סולר ידנית
    # בלבד). במקרה כזה אין DataFrame עם עמודות — מתייחסים ל-0 שעות לכל כלי.
    has_hours = (
        not df_hours_monthly.empty
        and {"license_num", "month", "total_work_hours"}.issubset(df_hours_monthly.columns)
    )
    if has_hours:
        merged = df_solar_monthly.merge(
            df_hours_monthly[["license_num", "month", "total_work_hours"]],
            on=["license_num", "month"],
            how="left",
        )
    else:
        merged = df_solar_monthly.copy()
        merged["total_work_hours"] = 0
    merged["total_work_hours"] = merged["total_work_hours"].fillna(0)
    merged = merged.merge(
        tools_registry[["license_num", "tool_type"]],
        on="license_num",
        how="left",
    )

    no_hours = merged[merged["total_work_hours"] == 0].copy()
    # מסנן כלי תמיכה
    no_hours = no_hours[~no_hours["tool_type"].isin(SUPPORT_TOOL_TYPES)]
    no_hours = no_hours[no_hours["total_liters"] > 0]
    if no_hours.empty:
        return pd.DataFrame(columns=cols)

    no_hours["estimated_waste_nis"] = (
        no_hours["total_liters"] * PRICE_PER_LITER_NIS
    ).round(2)
    return no_hours[cols].reset_index(drop=True)


def detect_excessive_hours(df_hours: pd.DataFrame) -> pd.DataFrame:
    """בדיקה 3: שעות עבודה חריגות (>14 ביום) או שליליות.

    Returns:
        DataFrame עם השורות הבעייתיות + סוג הדגל.
    """
    cols = ["date", "license_num", "tool_name", "work_hours", "flag_type"]
    if df_hours.empty:
        return pd.DataFrame(columns=cols)

    out = df_hours.copy()
    out["flag_type"] = ""
    out.loc[out["work_hours"] > MAX_WORK_HOURS_PER_DAY, "flag_type"] = "hours_excessive"
    out.loc[out["work_hours"] < 0, "flag_type"] = "hours_negative"
    flagged = out[out["flag_type"] != ""]
    return flagged[cols].reset_index(drop=True)


def detect_large_transactions(df_master: pd.DataFrame) -> pd.DataFrame:
    """בדיקה 4: תנועות בסכום > LARGE_TRANSACTION_NIS."""
    cols = ["project_id", "month", "date", "account_num", "account_name",
            "supplier", "amount", "description"]
    if df_master.empty:
        return pd.DataFrame(columns=cols)

    flagged = df_master[df_master["amount"].abs() > LARGE_TRANSACTION_NIS].copy()
    if flagged.empty:
        return pd.DataFrame(columns=cols)

    flagged = flagged.sort_values("amount", ascending=False)
    available = [c for c in cols if c in flagged.columns]
    return flagged[available].reset_index(drop=True)


def detect_unassigned_transactions(df_master: pd.DataFrame) -> pd.DataFrame:
    """בדיקה 6: תנועות 'יתומות' - ללא ספק וללא פרטים משמעותיים.

    קריטריון: source='chashbashevet' וגם supplier ריק וגם description קצר/ריק.
    תנועות כאלה לא ניתן לייחס לפעילות כלשהי - חשוד.
    """
    cols = ["project_id", "month", "date", "account_num", "account_name",
            "supplier", "description", "amount"]
    if df_master.empty:
        return pd.DataFrame(columns=cols)

    src_col = df_master.get("source", pd.Series(["chashbashevet"] * len(df_master)))
    mask_src = src_col == "chashbashevet"
    sup = df_master.get("supplier", pd.Series([""] * len(df_master))).fillna("").astype(str)
    desc = df_master.get("description", pd.Series([""] * len(df_master))).fillna("").astype(str)
    mask_empty = (sup.str.strip() == "") & (desc.str.strip().str.len() < 4)
    mask_significant = df_master["amount"].abs() > 1000  # רק חיובים משמעותיים

    flagged = df_master[mask_src & mask_empty & mask_significant].copy()
    if flagged.empty:
        return pd.DataFrame(columns=cols)
    available = [c for c in cols if c in flagged.columns]
    return flagged[available].reset_index(drop=True)


def detect_suspicious_descriptions(df_master: pd.DataFrame) -> pd.DataFrame:
    """בדיקה 5: תנועות עם מילות מפתח חשודות בתיאור."""
    cols = ["project_id", "month", "date", "account_num", "supplier",
            "amount", "description", "matched_keyword"]
    if df_master.empty or "description" not in df_master.columns:
        return pd.DataFrame(columns=cols)

    pattern = "|".join(SUSPICIOUS_KEYWORDS)
    desc = df_master["description"].fillna("").astype(str)
    mask = desc.str.contains(pattern, na=False)
    flagged = df_master[mask].copy()
    if flagged.empty:
        return pd.DataFrame(columns=cols)

    flagged["matched_keyword"] = desc[mask].apply(
        lambda s: next((kw for kw in SUSPICIOUS_KEYWORDS if kw in s), "")
    )
    available = [c for c in cols if c in flagged.columns]
    return flagged[available].reset_index(drop=True)


def run_all_checks(
    df_master: pd.DataFrame,
    df_solar_monthly: pd.DataFrame,
    df_hours_monthly: pd.DataFrame,
    tools_registry: pd.DataFrame,
    df_hours_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """מריץ את כל הבדיקות ומחזיר טבלת חריגות מאוחדת.

    Returns:
        DataFrame עם: project_id, month, check_type, severity,
        entity (license_num/account_num/supplier), details, estimated_impact_nis.
    """
    rows: list[dict] = []
    project_id = (
        df_master["project_id"].iloc[0] if not df_master.empty and "project_id" in df_master.columns else ""
    )

    # בדיקה 1
    excess = detect_solar_excess(df_solar_monthly, df_hours_monthly, tools_registry)
    for _, r in excess.iterrows():
        rows.append({
            "project_id": project_id,
            "month": r["month"],
            "check_type": "solar_excess",
            "severity": r["flag_severity"],
            "entity": str(r["license_num"]),
            "details": (
                f"{r['tool_name']}: {r['actual_lph']:.1f} ל'/ש' (תקן {r['norm_high']}), "
                f"חריגה של {r['excess_liters']:.0f} ליטר"
            ),
            "estimated_impact_nis": float(r["damage_estimate_nis"]),
        })

    # בדיקה 2
    no_hours = detect_solar_without_hours(df_solar_monthly, df_hours_monthly, tools_registry)
    for _, r in no_hours.iterrows():
        rows.append({
            "project_id": project_id,
            "month": r["month"],
            "check_type": "solar_without_hours",
            "severity": "medium",
            "entity": str(r["license_num"]),
            "details": f"{r['tool_name']}: {r['total_liters']:.0f} ליטר ללא שעות עבודה",
            "estimated_impact_nis": float(r["estimated_waste_nis"]),
        })

    # בדיקה 3 - מקבל את ה-daily אם נמסר, אחרת מדלג
    if df_hours_daily is not None and not df_hours_daily.empty:
        exc_hours = detect_excessive_hours(df_hours_daily)
        for _, r in exc_hours.iterrows():
            month = pd.to_datetime(r["date"]).strftime("%m-%Y")
            rows.append({
                "project_id": project_id,
                "month": month,
                "check_type": r["flag_type"],
                "severity": "low" if r["flag_type"] == "hours_excessive" else "high",
                "entity": str(r["license_num"]),
                "details": f"{r['tool_name']}: {r['work_hours']:.1f} שעות ב-{r['date'].date()}",
                "estimated_impact_nis": 0.0,
            })

    # בדיקה 4
    large = detect_large_transactions(df_master)
    for _, r in large.iterrows():
        rows.append({
            "project_id": r.get("project_id", project_id),
            "month": r.get("month", ""),
            "check_type": "large_transaction",
            "severity": "medium",
            "entity": str(r.get("account_num", "")),
            "details": f"{r.get('supplier', '')}: {r.get('description', '')} ({r['amount']:,.0f} ש\"ח)",
            "estimated_impact_nis": float(abs(r["amount"])),
        })

    # בדיקה 6 - תנועות יתומות
    orphans = detect_unassigned_transactions(df_master)
    for _, r in orphans.iterrows():
        rows.append({
            "project_id": r.get("project_id", project_id),
            "month": r.get("month", ""),
            "check_type": "unassigned_transaction",
            "severity": "medium",
            "entity": str(r.get("account_num", "")),
            "details": f"תנועה ללא ספק/פרטים: {r.get('account_name', '')} ({r['amount']:,.0f} ש\"ח)",
            "estimated_impact_nis": float(abs(r["amount"])),
        })

    # בדיקה 5
    susp = detect_suspicious_descriptions(df_master)
    for _, r in susp.iterrows():
        rows.append({
            "project_id": r.get("project_id", project_id),
            "month": r.get("month", ""),
            "check_type": "suspicious_description",
            "severity": "low",
            "entity": str(r.get("supplier", "")),
            "details": f"מילת מפתח '{r['matched_keyword']}': {r.get('description', '')}",
            "estimated_impact_nis": float(abs(r.get("amount", 0))),
        })

    if not rows:
        return pd.DataFrame(columns=ANOMALIES_COLS)
    return pd.DataFrame(rows, columns=ANOMALIES_COLS)


def flags_to_json(flags: list[dict]) -> str:
    """ממיר רשימת flags ל-JSON לאחסון בעמודה anomaly_flags."""
    if not flags:
        return ""
    return json.dumps(flags, ensure_ascii=False)


def apply_flags_to_master(
    df_master: pd.DataFrame,
    df_anomalies: pd.DataFrame,
) -> pd.DataFrame:
    """מוסיף עמודת anomaly_flags ל-master לפי תוצאות הבדיקות.

    מסמן שורות master שעולות בבדיקות 4 ו-5 (תנועות-ספציפיות).
    בדיקות 1-3 לא מקושרות לשורת master יחידה אלא ל-(כלי, חודש).
    """
    if df_master.empty:
        return df_master.assign(anomaly_flags="")

    df = df_master.copy()
    df["anomaly_flags"] = ""
    if df_anomalies.empty:
        return df

    # סמן large_transaction לפי amount
    large = df_anomalies[df_anomalies["check_type"] == "large_transaction"]
    if not large.empty:
        mask = df["amount"].abs() > LARGE_TRANSACTION_NIS
        df.loc[mask, "anomaly_flags"] = df.loc[mask, "anomaly_flags"].apply(
            lambda v: _append_flag(v, "large_transaction")
        )

    # סמן suspicious_description לפי תיאור
    pattern = "|".join(SUSPICIOUS_KEYWORDS)
    if "description" in df.columns:
        desc_mask = df["description"].fillna("").astype(str).str.contains(pattern, na=False)
        df.loc[desc_mask, "anomaly_flags"] = df.loc[desc_mask, "anomaly_flags"].apply(
            lambda v: _append_flag(v, "suspicious_description")
        )

    return df


def _append_flag(current: str, flag_name: str) -> str:
    """מוסיף flag לרשימת ה-flags הקיימת (JSON-encoded list)."""
    try:
        existing = json.loads(current) if current else []
    except json.JSONDecodeError:
        existing = []
    if flag_name not in existing:
        existing.append(flag_name)
    return json.dumps(existing, ensure_ascii=False)
