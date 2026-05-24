"""אורקסטרציה ראשית - חוט השני בין loaders, aggregator, anomaly detector ו-master.

זרימה טיפוסית:
    1. list_available_projects() / list_available_months(project_id)
    2. load_project_month(project_id, month) → dict עם chashbashevet/solar/hours.
    3. aggregate_month(loaded) → DataFrame בסכמת master.
    4. detect_anomalies(df) → מוסיף עמודת anomaly_flags.
    5. build_master() → מאגד את כל החודשים של כל הפרויקטים, שומר ל-parquet.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core import (
    anomaly_detector,
    categorizer,
    chashbashevet_loader,
    fuel_inventory,
    hours_loader,
    site_tracking_loader,
    solar_loader,
)

logger = logging.getLogger(__name__)


# ── נתיבים קבועים ─────────────────────────────────────────────
# Anchor everything to the project root (this file's parent) so paths
# work regardless of where streamlit was invoked from (local vs cloud).
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_ROOT = PROJECT_ROOT / "data"
PROJECTS_ROOT = DATA_ROOT / "projects"
PROJECTS_REGISTRY = DATA_ROOT / "projects_registry.xlsx"
TOOLS_REGISTRY = DATA_ROOT / "tools_registry.xlsx"
MASTER_PARQUET = DATA_ROOT / "master.parquet"
CACHE_ROOT = PROJECT_ROOT / "output" / "cache"


# ── סכמת master.parquet ───────────────────────────────────────
MASTER_SCHEMA_COLS = [
    "project_id", "project_name", "month", "date",
    "category", "subcategory",
    "account_num", "account_name",
    "supplier", "description",
    "amount", "source", "anomaly_flags",
    # סולר
    "license_num", "tool_name", "liters", "engine_hours",
    # שעות
    "work_hours",
]


def list_available_projects() -> list[dict]:
    """מחזיר רשימת פרויקטים פעילים מתוך projects_registry.xlsx.

    Returns:
        רשימת dicts עם: project_id, project_name, site_name (לסינון solar), status.
    """
    if not PROJECTS_REGISTRY.exists():
        logger.warning("projects_registry.xlsx not found at %s", PROJECTS_REGISTRY)
        return []
    try:
        df = pd.read_excel(PROJECTS_REGISTRY)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.exception("Failed to load projects_registry: %s", e)
        return []


def list_available_months(project_id: str) -> list[str]:
    """מחזיר רשימת חודשים זמינים לפרויקט (תיקיות MM-YYYY).

    Returns:
        רשימה ממוינת של מחרוזות "MM-YYYY".
    """
    project_dir = PROJECTS_ROOT / project_id
    if not project_dir.exists():
        return []
    months = [d.name for d in project_dir.iterdir() if d.is_dir() and "-" in d.name]
    return sorted(months)


SITE_TRACKING_PARQUET = DATA_ROOT / "site_tracking.parquet"


def load_project_site_tracking(project_id: str) -> dict[str, pd.DataFrame]:
    """טוען site_tracking.xlsx לפרויקט (project-wide, לא per-month).

    מאתר את הקובץ ב-data/projects/<id>/site_tracking.xlsx או לפי
    שמות עבריים נפוצים ("מעקב אתר", "site_tracking").
    """
    project_dir = PROJECTS_ROOT / project_id
    if not project_dir.exists():
        return {k: pd.DataFrame() for k in site_tracking_loader.SHEET_KEYS}

    candidate = project_dir / "site_tracking.xlsx"
    if not candidate.exists():
        for f in project_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
                continue
            if f.name.startswith("~$"):
                continue
            name_lower = f.name.lower()
            if any(kw in name_lower for kw in ["site_tracking", "מעקב אתר", "מעקב"]):
                candidate = f
                break
    return site_tracking_loader.load_site_tracking(candidate)


def build_site_tracking_parquet() -> None:
    """אוסף את site_tracking מכל הפרויקטים ושומר ל-parquet אחד עם sheet column.

    מאפשר ל-Streamlit Cloud לראות את הנתונים בלי לטעון את ה-xlsx
    (שהוא local-only כי הוא בתיקייה גיט-איגנור).
    """
    all_frames: list[pd.DataFrame] = []
    for p in list_available_projects():
        pid = p["project_id"]
        data = load_project_site_tracking(pid)
        for sheet_key, df in data.items():
            if df.empty:
                continue
            tagged = df.copy()
            tagged["project_id"] = pid
            tagged["sheet_key"] = sheet_key
            all_frames.append(tagged)
    if not all_frames:
        logger.info("No site_tracking data found across any project")
        return
    combined = pd.concat(all_frames, ignore_index=True, sort=False)

    # Normalize object columns to string (xlsx import may produce
    # mixed types like datetime+string in the same column).
    # Keep numeric and datetime cols as-is.
    for col in combined.columns:
        if combined[col].dtype == "object":
            combined[col] = combined[col].astype(str).replace("nan", "").replace("NaT", "")

    SITE_TRACKING_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    try:
        combined.to_parquet(SITE_TRACKING_PARQUET, index=False)
        logger.info("Saved site_tracking parquet (%d rows) to %s",
                    len(combined), SITE_TRACKING_PARQUET)
    except Exception as e:
        logger.exception("Failed to save site_tracking parquet: %s", e)


def load_site_tracking_data(project_id: str | None = None) -> dict[str, pd.DataFrame]:
    """קורא site_tracking.parquet ומחזיר dict לפי sheet_key.

    משמש את ה-app בענן (שאין לו את ה-xlsx המקורי).
    Fallback: אם ה-parquet לא קיים, מנסה לקרוא את ה-xlsx המקורי.
    """
    if SITE_TRACKING_PARQUET.exists():
        try:
            df = pd.read_parquet(SITE_TRACKING_PARQUET)
            if project_id and "project_id" in df.columns:
                df = df[df["project_id"] == project_id]
            return {
                key: grp.drop(columns=["sheet_key"], errors="ignore").reset_index(drop=True)
                for key, grp in df.groupby("sheet_key")
            }
        except Exception as e:
            logger.warning("Failed to load site_tracking parquet, falling back: %s", e)
    # Fallback to xlsx
    if project_id:
        return load_project_site_tracking(project_id)
    return {k: pd.DataFrame() for k in site_tracking_loader.SHEET_KEYS}


def _project_meta(project_id: str) -> dict:
    """מאחזר project_name + site_name לפרויקט."""
    projects = list_available_projects()
    for p in projects:
        if p.get("project_id") == project_id:
            return p
    return {"project_id": project_id, "project_name": project_id, "site_name": project_id}


def _find_file(month_dir: Path, keywords: list[str], explicit_name: str | None = None) -> Path | None:
    """מאתר קובץ בתיקייה לפי שם מדויק או לפי מילות מפתח בעברית/אנגלית.

    תומך בשמות כמו 'chashbashevet.xlsx', 'כרטיס 12.25.xlsx', 'מאזן 03.26.xlsx'.
    """
    if explicit_name:
        p = month_dir / explicit_name
        if p.exists():
            return p
    if not month_dir.exists():
        return None
    for f in month_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xls"):
            continue
        # קבצי lock של Excel (~$...) - דלג
        if f.name.startswith("~$"):
            continue
        name_lower = f.name.lower()
        for kw in keywords:
            if kw.lower() in name_lower:
                return f
    return None


def load_project_month(project_id: str, month: str) -> dict[str, pd.DataFrame]:
    """טוען את כל נתוני חודש בודד בפרויקט בודד.

    מאתר קבצים אוטומטית לפי מילות מפתח בשם הקובץ:
        כרטיס / chashbashevet → כרטיס הנהלה
        מאזן  / balance       → מאזן בוחן (placeholder - לא נטען עדיין)
        solar / סולר / תדלוק  → דוח תדלוק
        hours / שעות          → דוח שעות

    Args:
        project_id: מזהה הפרויקט (תואם שם תיקייה ב-data/projects/).
        month: "MM-YYYY".

    Returns:
        dict עם המפתחות (כל ערך DataFrame, ריק אם הקובץ לא קיים):
            chashbashevet, solar, hours.
    """
    month_dir = PROJECTS_ROOT / project_id / month
    meta = _project_meta(project_id)
    site_name = meta.get("site_name", project_id)

    out: dict[str, pd.DataFrame] = {}

    chash_path = _find_file(month_dir, ["chashbashevet", "כרטיס"], "chashbashevet.xlsx")
    out["chashbashevet"] = (
        chashbashevet_loader.load_chashbashevet(chash_path)
        if chash_path
        else pd.DataFrame(columns=chashbashevet_loader.OUTPUT_COLS)
    )

    solar_path = _find_file(month_dir, ["solar", "סולר", "תדלוק"], "solar.xlsx")
    out["solar"] = (
        solar_loader.load_solar(solar_path, site_name)
        if solar_path
        else pd.DataFrame(columns=solar_loader.OUTPUT_COLS)
    )

    hours_path = _find_file(month_dir, ["hours", "שעות"], "hours.xlsx")
    out["hours"] = (
        hours_loader.load_hours(hours_path)
        if hours_path
        else pd.DataFrame(columns=hours_loader.OUTPUT_COLS)
    )

    # מאזן מלאי סולר (אופציונלי)
    inv_path = _find_file(month_dir, ["fuel_inventory", "מלאי סולר", "מלאי"],
                          "fuel_inventory.xlsx")
    out["fuel_inventory"] = (
        fuel_inventory.load_fuel_inventory(inv_path)
        if inv_path
        else pd.DataFrame(columns=fuel_inventory.OUTPUT_COLS)
    )

    logger.info(
        "Loaded %s/%s: chash=%d, solar=%d, hours=%d",
        project_id, month,
        len(out["chashbashevet"]), len(out["solar"]), len(out["hours"]),
    )
    return out


def aggregate_month(
    loaded: dict[str, pd.DataFrame],
    project_id: str,
    project_name: str,
    month: str,
) -> pd.DataFrame:
    """ממזג את נתוני החודש לסכמת master.

    מוסיף project_id/project_name/month לכל שורה, מסווג חשבונות לקטגוריות.
    """
    frames: list[pd.DataFrame] = []

    # 1) חשבשבת - הליבה
    chash = loaded.get("chashbashevet", pd.DataFrame())
    if not chash.empty:
        chash = categorizer.categorize_dataframe(chash, account_col="account_num")
        chash_rows = pd.DataFrame({
            "project_id": project_id,
            "project_name": project_name,
            "month": month,
            "date": chash["date"],
            "category": chash["category"],
            "subcategory": chash["subcategory"],
            "account_num": chash["account_num"],
            "account_name": chash["account_name"],
            "supplier": chash["supplier"],
            "description": chash["details"],
            "amount": chash["amount"],
            "source": "chashbashevet",
            "anomaly_flags": "",
        })
        frames.append(chash_rows)

    # 2) סולר - כל תדלוק נשמר כשורה (amount=0, נתוני סולר בעמודות הייעודיות)
    solar = loaded.get("solar", pd.DataFrame())
    if not solar.empty:
        solar_rows = pd.DataFrame({
            "project_id": project_id,
            "project_name": project_name,
            "month": month,
            "date": solar["date"],
            "category": "סולר וצמ\"ה",
            "subcategory": "תדלוק",
            "account_num": pd.NA,
            "account_name": "",
            "supplier": "",
            "description": solar["tool_name"].astype(str),
            "amount": 0.0,
            "source": "solar",
            "anomaly_flags": "",
            "license_num": solar["license_num"],
            "tool_name": solar["tool_name"],
            "liters": solar["liters"],
            "engine_hours": solar["engine_hours"],
        })
        frames.append(solar_rows)

    # 3) שעות - כל יום עבודה נשמר כשורה
    hours = loaded.get("hours", pd.DataFrame())
    if not hours.empty:
        hours_rows = pd.DataFrame({
            "project_id": project_id,
            "project_name": project_name,
            "month": month,
            "date": hours["date"],
            "category": "שעות עבודה",
            "subcategory": "",
            "account_num": pd.NA,
            "account_name": "",
            "supplier": "",
            "description": hours["tool_name"].astype(str),
            "amount": 0.0,
            "source": "hours",
            "anomaly_flags": "",
            "license_num": hours["license_num"],
            "tool_name": hours["tool_name"],
            "work_hours": hours["work_hours"],
        })
        frames.append(hours_rows)

    if not frames:
        return pd.DataFrame(columns=MASTER_SCHEMA_COLS)

    df = pd.concat(frames, ignore_index=True, sort=False)
    # ודא שכל עמודות הסכמה קיימות
    for col in MASTER_SCHEMA_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[MASTER_SCHEMA_COLS]


def _load_tools_registry() -> pd.DataFrame:
    """טוען את tools_registry.

    ממזג tools_registry.xlsx (seed) עם control_db.tools_registry (mutable).
    SQLite גובר על xlsx במקרה של חפיפה.
    """
    try:
        from core import control_db
        merged = control_db.merged_tools_registry(TOOLS_REGISTRY if TOOLS_REGISTRY.exists() else None)
        if "license_num" in merged.columns:
            merged["license_num"] = pd.to_numeric(merged["license_num"], errors="coerce").astype("Int64")
        return merged
    except Exception as e:
        logger.exception("Failed to load merged tools_registry: %s", e)
        # Fallback to xlsx-only
        if TOOLS_REGISTRY.exists():
            try:
                df = pd.read_excel(TOOLS_REGISTRY)
                df["license_num"] = pd.to_numeric(df["license_num"], errors="coerce").astype("Int64")
                return df
            except Exception:
                pass
        return pd.DataFrame(columns=["license_num", "tool_name", "tool_type", "norm_low", "norm_high"])


def detect_anomalies(df_month: pd.DataFrame, tools_registry: pd.DataFrame | None = None) -> pd.DataFrame:
    """מוסיף עמודת anomaly_flags לשורות שמזוהות כחריגות.

    אינו מסנן - רק מסמן. הסינון נעשה בדשבורד.
    """
    if df_month.empty:
        return df_month

    if tools_registry is None:
        tools_registry = _load_tools_registry()

    # חישוב אגרגציות סולר/שעות לצורך בדיקות 1-2
    solar_rows = df_month[df_month["source"] == "solar"]
    hours_rows = df_month[df_month["source"] == "hours"]

    df_solar_monthly = solar_loader.aggregate_by_tool_month(
        solar_rows.rename(columns={"liters": "liters"})
    ) if not solar_rows.empty else pd.DataFrame()

    df_hours_monthly = hours_loader.aggregate_by_tool_month(
        hours_rows
    ) if not hours_rows.empty else pd.DataFrame()

    # שורות חשבשבת בלבד לבדיקות 4-5
    chash_rows = df_month[df_month["source"] == "chashbashevet"]

    anomalies = anomaly_detector.run_all_checks(
        df_master=chash_rows,
        df_solar_monthly=df_solar_monthly,
        df_hours_monthly=df_hours_monthly,
        tools_registry=tools_registry,
        df_hours_daily=hours_rows,
    )

    df_flagged = anomaly_detector.apply_flags_to_master(df_month, anomalies)
    return df_flagged


def build_master() -> pd.DataFrame:
    """בונה מאסטר מלא של כל הפרויקטים × כל החודשים, שומר ל-parquet.

    Returns:
        ה-DataFrame המלא (גם נשמר ל-data/master.parquet).
    """
    tools = _load_tools_registry()
    all_rows: list[pd.DataFrame] = []

    projects = list_available_projects()
    for proj in projects:
        project_id = proj["project_id"]
        project_name = proj.get("project_name", project_id)
        for month in list_available_months(project_id):
            loaded = load_project_month(project_id, month)
            df = aggregate_month(loaded, project_id, project_name, month)
            if df.empty:
                continue
            df = detect_anomalies(df, tools)
            all_rows.append(df)
            logger.info("Built %d rows for %s/%s", len(df), project_id, month)

    if not all_rows:
        logger.warning("No data found for any project")
        master = pd.DataFrame(columns=MASTER_SCHEMA_COLS)
    else:
        master = pd.concat(all_rows, ignore_index=True, sort=False)

    try:
        MASTER_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        master.to_parquet(MASTER_PARQUET, index=False)
        logger.info("Saved master with %d rows to %s", len(master), MASTER_PARQUET)
    except Exception as e:
        logger.exception("Failed to save master parquet: %s", e)

    # Mirror to SQLite (audit + queryable). Parquet stays primary for now;
    # SQLite is additive — failures here don't break the pipeline.
    try:
        from core import db
        n_db = db.upsert_master(master)
        db.log_event("build_master", {
            "rows": len(master),
            "projects": int(master["project_id"].nunique()) if not master.empty else 0,
            "months": int(master["month"].nunique()) if not master.empty else 0,
        })
        logger.info("Mirrored %d rows to SQLite", n_db)
    except Exception as e:
        logger.exception("SQLite mirror failed (non-fatal): %s", e)

    # Build site_tracking parquet so cloud can render the operational data
    try:
        build_site_tracking_parquet()
    except Exception as e:
        logger.exception("site_tracking parquet build failed (non-fatal): %s", e)

    return master


def load_master() -> pd.DataFrame:
    """טוען את master.parquet אם קיים. אחרת מחזיר DataFrame ריק עם הסכמה."""
    if MASTER_PARQUET.exists():
        try:
            return pd.read_parquet(MASTER_PARQUET)
        except Exception as e:
            logger.exception("Failed to load master parquet: %s", e)
    return pd.DataFrame(columns=MASTER_SCHEMA_COLS)


def run_month(project_id: str, month: str) -> pd.DataFrame:
    """End-to-end לחודש בודד: load → aggregate → detect anomalies.

    שימושי לבדיקה מהירה של חודש לפני build_master מלא.
    """
    meta = _project_meta(project_id)
    loaded = load_project_month(project_id, month)
    df = aggregate_month(loaded, project_id, meta.get("project_name", project_id), month)
    if df.empty:
        return df
    return detect_anomalies(df, _load_tools_registry())
