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
    balance_loader,
    balance_store,
    categorizer,
    chashbashevet_loader,
    fuel_inventory,
    fuel_invoices_loader,
    fuel_tracker_loader,
    hours_loader,
    ledger_store,
    manual_store,
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
# נתונים שהוזנו ידנית — אחסון קבוע *עוקב-git* (לא תחת projects/ שמוחרג).
# מסונכרן לענן ב-push, וניתן לפתיחה/גיבוי ידני (xlsx).
MANUAL_ROOT = DATA_ROOT / "manual"
PROJECTS_REGISTRY = DATA_ROOT / "projects_registry.xlsx"
TOOLS_REGISTRY = DATA_ROOT / "tools_registry.xlsx"
MASTER_PARQUET = DATA_ROOT / "master.parquet"
CACHE_ROOT = PROJECT_ROOT / "output" / "cache"


# ── סכמת master.parquet ───────────────────────────────────────
MASTER_SCHEMA_COLS = [
    "project_id", "project_name", "month", "date",
    # תאריך המסמך/אסמכתא (הקובע לחודש) + תאריך הערך (סליקה — לא לשיוך חודש)
    "document_date", "value_date",
    "category", "subcategory",
    "account_num", "account_name",
    "supplier", "description",
    "amount", "source", "anomaly_flags",
    # debit/credit הפרטניים מחשבשבת (שומר את הפיצול לצורך reconciliation)
    "debit", "credit",
    # שדות סיווג מ-classify_transaction (תקפים רק לשורות chashbashevet)
    "account_type", "main_category", "sub_category",
    "net_amount", "signed_amount", "is_credit_note",
    "classification_confidence", "classification_note",
    # סולר
    "license_num", "tool_name", "liters", "engine_hours",
    # שעות
    "work_hours",
]

# עמודות מספריות (float) בסכמת master. משמש לייצוב dtype אחרי pd.concat —
# concat של מסגרת שחסרה ערך באחת מהן (NaN/NA) עלול לשדרג עמודה ל-object,
# ומאז כל ניסיון .round()/חישוב נומרי קורס. תמיד נכפה אותן חזרה ל-float.
MASTER_NUMERIC_COLS = [
    "amount", "debit", "credit", "net_amount", "signed_amount",
    "liters", "engine_hours", "work_hours",
]


def coerce_master_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """מכריח את עמודות הכסף/הכמויות חזרה ל-float64 (NaN לערכים חסרים).

    מונע באג dtype=object שנוצר כש-pd.concat ממזג מסגרות שחלקן חסרות
    ערך מספרי — מה שגרם ל-TypeError ב-.round() בטאב בקרת איכות.
    אינו משנה ערכים, רק טיפוס.
    """
    if df is None or df.empty:
        return df
    for col in MASTER_NUMERIC_COLS:
        if col in df.columns and df[col].dtype == object:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def list_available_projects() -> list[dict]:
    """מחזיר רשימת פרויקטים פעילים מתוך projects_registry.xlsx.

    Returns:
        רשימת dicts עם: project_id, project_name, site_name (לסינון solar), status.
    """
    # דרך project_store — מקור-לאמת מאוחד (Neon אם מוגדר, אחרת xlsx). כך
    # עריכות שנשמרו בענן (שם לקוח/סטטוס) מופיעות גם בסיידבר וב-build_master.
    try:
        from core import project_store
        df = project_store.load_projects_registry()
        if df is None or df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception as e:
        logger.exception("Failed to load projects via project_store: %s", e)

    # fallback ישיר ל-xlsx אם משהו נכשל בשכבת project_store
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
FUEL_INVOICES_XLSX = DATA_ROOT / "fuel_invoices.xlsx"
FUEL_INVOICES_PARQUET = DATA_ROOT / "fuel_invoices.parquet"
FUEL_TRACKER_PARQUET = DATA_ROOT / "fuel_tracker.parquet"


def build_fuel_invoices_parquet() -> None:
    """טוען את fuel_invoices.xlsx ושומר ל-parquet (לענן)."""
    if not FUEL_INVOICES_XLSX.exists():
        logger.info("fuel_invoices.xlsx not present — skipping parquet build")
        return
    df = fuel_invoices_loader.load_fuel_invoices(FUEL_INVOICES_XLSX)
    if df.empty:
        return
    df = df.copy()
    # Normalize types for parquet
    if "site_code" in df.columns:
        df["site_code"] = df["site_code"].astype("Int64")
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str).replace("nan", "").replace("NaT", "")
    df.to_parquet(FUEL_INVOICES_PARQUET, index=False)
    logger.info("Saved fuel_invoices parquet (%d rows) to %s",
                len(df), FUEL_INVOICES_PARQUET)


def load_fuel_invoices_data(project_id: str | None = None) -> pd.DataFrame:
    """קורא fuel_invoices.parquet; fallback ל-xlsx."""
    if FUEL_INVOICES_PARQUET.exists():
        try:
            df = pd.read_parquet(FUEL_INVOICES_PARQUET)
            # date back to datetime
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            if project_id:
                df = df[df["project_id"] == project_id]
            return df.reset_index(drop=True)
        except Exception as e:
            logger.warning("Failed to load fuel_invoices parquet: %s", e)
    # Fallback
    df = fuel_invoices_loader.load_fuel_invoices(FUEL_INVOICES_XLSX)
    if project_id:
        df = fuel_invoices_loader.filter_by_project(df, project_id)
    return df


def load_project_balances(project_id: str) -> pd.DataFrame:
    """אוסף מאזן בוחן מכל החודשים של פרויקט. מוסיף עמודת month."""
    project_dir = PROJECTS_ROOT / project_id
    if not project_dir.exists():
        return pd.DataFrame(columns=balance_loader.OUTPUT_COLS + ["month"])

    frames = []
    for month_dir in sorted(project_dir.iterdir()):
        if not month_dir.is_dir() or "-" not in month_dir.name:
            continue
        bp = _find_file(month_dir, ["balance", "מאזן"], "balance.xlsx")
        if bp and "fuel_inventory" in bp.name.lower():
            bp = None
        if not bp:
            continue
        df = balance_loader.load_balance(bp)
        if df.empty:
            continue
        df = df.copy()
        df["month"] = month_dir.name
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=balance_loader.OUTPUT_COLS + ["month"])
    return pd.concat(frames, ignore_index=True, sort=False)


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


def build_fuel_tracker_parquet() -> None:
    """אוסף את "מעקב סולר וטיפולים — כלי צמה.xlsx" מכל הפרויקטים ל-parquet.

    הקובץ הזה הוא המקור החי לתדלוקים (גליון "יומן סולר" עם כל
    האירועים: ליטרים, שעות מנוע, ספירת שעות, צריכה, סטטוס חריגה).

    כמו site_tracking — ה-xlsx local-only (gitignored), והפרקט נדחף
    לענן כדי ש-Streamlit Cloud יראה את הנתונים.
    """
    all_frames: list[pd.DataFrame] = []
    for p in list_available_projects():
        pid = p["project_id"]
        site_name = p.get("site_name") or p.get("project_name") or pid
        project_dir = PROJECTS_ROOT / pid
        df = fuel_tracker_loader.load_fuel_tracker(project_dir, site_name=site_name)
        if df.empty:
            continue
        # apply system classification (status + lph_display)
        df = fuel_tracker_loader.apply_classification(df)
        df["project_id"] = pid
        all_frames.append(df)
    if not all_frames:
        logger.info("No fuel_tracker data found across any project")
        # Write an empty marker parquet so loader knows there's no data
        empty = pd.DataFrame(columns=list(fuel_tracker_loader.OUTPUT_COLS) +
                              ["status", "lph_display", "project_id"])
        FUEL_TRACKER_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        try:
            empty.to_parquet(FUEL_TRACKER_PARQUET, index=False)
        except Exception:
            pass
        return
    combined = pd.concat(all_frames, ignore_index=True, sort=False)

    FUEL_TRACKER_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    try:
        combined.to_parquet(FUEL_TRACKER_PARQUET, index=False)
        logger.info("Saved fuel_tracker parquet (%d rows) to %s",
                    len(combined), FUEL_TRACKER_PARQUET)
    except Exception as e:
        logger.exception("Failed to save fuel_tracker parquet: %s", e)


def load_fuel_tracker_data(project_id: str | None = None) -> pd.DataFrame:
    """קורא fuel_tracker.parquet ומחזיר DataFrame מסונן לפרויקט.

    משמש את הדשבורד (גם בענן וגם מקומית). Fallback ל-xlsx אם
    הפרקט לא קיים — שימושי במצב פיתוח לפני הרצת build_master.
    """
    if FUEL_TRACKER_PARQUET.exists():
        try:
            df = pd.read_parquet(FUEL_TRACKER_PARQUET)
            if project_id and "project_id" in df.columns:
                df = df[df["project_id"] == project_id].reset_index(drop=True)
            return df
        except Exception as e:
            logger.warning("Failed to load fuel_tracker parquet, falling back: %s", e)
    # Fallback: read xlsx directly (slow, dev-only)
    if project_id:
        project_dir = PROJECTS_ROOT / project_id
        site_name = _project_meta(project_id).get("site_name") or project_id
        df = fuel_tracker_loader.load_fuel_tracker(project_dir, site_name=site_name)
        return fuel_tracker_loader.apply_classification(df)
    return pd.DataFrame(columns=list(fuel_tracker_loader.OUTPUT_COLS) +
                         ["status", "lph_display", "project_id"])


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

    def _log(path: Path | None, file_type: str, rows: int) -> None:
        """רישום ייבוא ל-imported_files - בטוח לכשלון (לא קריטי לפייפליין)."""
        if not path:
            return
        try:
            from core import storage
            storage.save_imported_file(path, project_id, month, file_type,
                                         rows_loaded=rows, status="imported")
        except Exception as e:
            logger.warning("storage logging failed for %s: %s", path, e)

    chash_path = _find_file(month_dir, ["chashbashevet", "כרטיס"], "chashbashevet.xlsx")
    out["chashbashevet"] = (
        chashbashevet_loader.load_chashbashevet(chash_path)
        if chash_path
        else pd.DataFrame(columns=chashbashevet_loader.OUTPUT_COLS)
    )
    _log(chash_path, "chashbashevet", len(out["chashbashevet"]))

    solar_path = _find_file(month_dir, ["solar", "סולר", "תדלוק"], "solar.xlsx")
    out["solar"] = (
        solar_loader.load_solar(solar_path, site_name)
        if solar_path
        else pd.DataFrame(columns=solar_loader.OUTPUT_COLS)
    )
    _log(solar_path, "solar", len(out["solar"]))

    hours_path = _find_file(month_dir, ["hours", "שעות"], "hours.xlsx")
    out["hours"] = (
        hours_loader.load_hours(hours_path)
        if hours_path
        else pd.DataFrame(columns=hours_loader.OUTPUT_COLS)
    )
    _log(hours_path, "hours", len(out["hours"]))

    # מאזן בוחן (אופציונלי, end-of-month balance — משלים את הכרטיס)
    balance_path = _find_file(month_dir, ["balance", "מאזן"], "balance.xlsx")
    # אבל לא להתבלבל עם "fuel_inventory" שמכיל גם "מלאי" - תסנן
    if balance_path and "fuel_inventory" in balance_path.name.lower():
        balance_path = None
    out["balance"] = (
        balance_loader.load_balance(balance_path)
        if balance_path
        else pd.DataFrame(columns=balance_loader.OUTPUT_COLS)
    )
    _log(balance_path, "balance", len(out["balance"]))

    # מאזן מלאי סולר (אופציונלי)
    inv_path = _find_file(month_dir, ["fuel_inventory", "מלאי סולר"],
                          "fuel_inventory.xlsx")
    out["fuel_inventory"] = (
        fuel_inventory.load_fuel_inventory(inv_path)
        if inv_path
        else pd.DataFrame(columns=fuel_inventory.OUTPUT_COLS)
    )
    _log(inv_path, "fuel_inventory", len(out["fuel_inventory"]))

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
    include_chashbashevet: bool = True,
) -> pd.DataFrame:
    """ממזג את נתוני החודש לסכמת master.

    מוסיף project_id/project_name/month לכל שורה, מסווג חשבונות לקטגוריות.

    include_chashbashevet=False מדלג על שורות הכרטיס מהתיקייה — משמש
    כשהכרטסת מגיעה ממאגר התנועות המצטבר (ledger_store) במקום מקבצי החודש.
    """
    frames: list[pd.DataFrame] = []

    # 1) חשבשבת - הליבה
    chash = loaded.get("chashbashevet", pd.DataFrame())
    if not include_chashbashevet:
        chash = pd.DataFrame()
    if not chash.empty:
        chash = categorizer.categorize_dataframe(chash, account_col="account_num")
        chash_rows = pd.DataFrame({
            "project_id": project_id,
            "project_name": project_name,
            "month": month,
            "date": chash["date"],
            "document_date": chash.get("document_date", chash["date"]),
            "value_date": chash.get("value_date", pd.NaT),
            # category/subcategory תאימות לאחור: מעתה ערכי main_category/sub_category
            "category": chash.get("main_category", chash.get("category", "")),
            "subcategory": chash.get("sub_category", chash.get("subcategory", "")),
            "account_num": chash["account_num"],
            "account_name": chash["account_name"],
            "supplier": chash["supplier"],
            "description": chash["details"],
            "amount": chash["amount"],
            "debit": chash["debit"],
            "credit": chash["credit"],
            # שדות סיווג חדשים
            "account_type": chash.get("account_type", "unknown"),
            "main_category": chash.get("main_category", ""),
            "sub_category": chash.get("sub_category", ""),
            "net_amount": chash.get("net_amount", chash["amount"]),
            "signed_amount": chash.get("signed_amount", chash["amount"]),
            "is_credit_note": chash.get("is_credit_note", False),
            "classification_confidence": chash.get("classification_confidence", "high"),
            "classification_note": chash.get("classification_note", ""),
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
            "document_date": solar["date"],
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
            "document_date": hours["date"],
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


def aggregate_store_chashbashevet(project_id: str, project_name: str) -> pd.DataFrame:
    """ממיר את מאגר התנועות המצטבר (ledger_store) לשורות בסכמת master.

    כל שורה מקבלת month לפי *תאריך התנועה* (לא לפי מועד ההעלאה).
    מחזיר ריק אם אין מאגר לפרויקט.
    """
    store = ledger_store.load_store(project_id)
    if store.empty:
        return pd.DataFrame(columns=MASTER_SCHEMA_COLS)

    store = store.copy()
    # month לפי תאריך התנועה (מקור האמת לסינון החודשי בכל הטאבים)
    dt = pd.to_datetime(store["date"], errors="coerce")
    months = dt.dt.strftime("%m-%Y")

    def _col(name, default=pd.NA):
        return store[name] if name in store.columns else pd.Series(default, index=store.index)

    rows = pd.DataFrame({
        "project_id": project_id,
        "project_name": project_name,
        "month": months,
        "date": dt,
        "document_date": _col("document_date", dt),
        "value_date": _col("value_date", pd.NaT),
        "category": _col("main_category", _col("category", "")),
        "subcategory": _col("sub_category", _col("subcategory", "")),
        "account_num": _col("account_num"),
        "account_name": _col("account_name", ""),
        "supplier": _col("supplier", ""),
        "description": _col("details", ""),
        "amount": _col("amount", 0.0),
        "debit": _col("debit", 0.0),
        "credit": _col("credit", 0.0),
        "account_type": _col("account_type", "unknown"),
        "main_category": _col("main_category", ""),
        "sub_category": _col("sub_category", ""),
        "net_amount": _col("net_amount", _col("amount", 0.0)),
        "signed_amount": _col("signed_amount", _col("amount", 0.0)),
        "is_credit_note": _col("is_credit_note", False),
        "classification_confidence": _col("classification_confidence", "high"),
        "classification_note": _col("classification_note", ""),
        "source": "chashbashevet",
        "anomaly_flags": "",
    })
    # שורות ללא תאריך תקין — דלג (יסומנו כשגיאה בעת היבוא)
    rows = rows[rows["month"].notna()]
    for col in MASTER_SCHEMA_COLS:
        if col not in rows.columns:
            rows[col] = pd.NA
    return rows[MASTER_SCHEMA_COLS].reset_index(drop=True)


def aggregate_manual_solar(project_id: str, project_name: str,
                           store: pd.DataFrame | None = None) -> pd.DataFrame:
    """ממיר את מאגר הסולר הידני (manual_store) לשורות בסכמת master.

    כל שורה: source="solar", amount=0.0 (העלות מגיעה מהכרטסת —
    לא לכפול), עם liters/license_num/tool_name בעמודות הייעודיות.
    החודש נגזר מתאריך השורה.

    store: אם סופק (למשל מ-Neon) — משמש במקום load_store המקומי.
    """
    if store is None:
        store = manual_store.load_store(project_id, "solar")
    if store.empty or "date" not in store.columns:
        return pd.DataFrame(columns=MASTER_SCHEMA_COLS)

    store = store.copy()
    dt = pd.to_datetime(store["date"], errors="coerce")
    months = dt.dt.strftime("%m-%Y")

    def _col(name, default=pd.NA):
        return store[name] if name in store.columns else pd.Series(default, index=store.index)

    rows = pd.DataFrame({
        "project_id": project_id,
        "project_name": project_name,
        "month": months,
        "date": dt,
        "document_date": dt,
        "category": "סולר וצמ\"ה",
        "subcategory": _col("fuel_type", "תדלוק"),
        "account_num": pd.NA,
        "account_name": "",
        "supplier": _col("supplier", ""),
        "description": _col("tool_name", "").astype(str),
        "amount": 0.0,
        "net_amount": 0.0,
        "signed_amount": 0.0,
        "source": "solar",
        "anomaly_flags": "",
        "license_num": _col("license_num"),
        "tool_name": _col("tool_name", ""),
        "liters": _col("liters", 0.0),
    })
    rows = rows[rows["month"].notna()]
    for col in MASTER_SCHEMA_COLS:
        if col not in rows.columns:
            rows[col] = pd.NA
    return rows[MASTER_SCHEMA_COLS].reset_index(drop=True)


def aggregate_manual_hours(project_id: str, project_name: str,
                           store: pd.DataFrame | None = None) -> pd.DataFrame:
    """ממיר את מאגר השעות הידני (manual_store) לשורות בסכמת master.

    כל שורה: source="hours", amount=0.0, work_hours=total_hours,
    tool_name=שם העובד (כדי שיופיע בטאב שעות). החודש נגזר מתאריך השורה.

    store: אם סופק (למשל מ-Neon) — משמש במקום load_store המקומי.
    """
    if store is None:
        store = manual_store.load_store(project_id, "hours")
    if store.empty or "date" not in store.columns:
        return pd.DataFrame(columns=MASTER_SCHEMA_COLS)

    store = store.copy()
    dt = pd.to_datetime(store["date"], errors="coerce")
    months = dt.dt.strftime("%m-%Y")

    def _col(name, default=pd.NA):
        return store[name] if name in store.columns else pd.Series(default, index=store.index)

    rows = pd.DataFrame({
        "project_id": project_id,
        "project_name": project_name,
        "month": months,
        "date": dt,
        "document_date": dt,
        "category": "שעות עבודה",
        "subcategory": _col("work_type", ""),
        "account_num": pd.NA,
        "account_name": "",
        "supplier": "",
        "description": _col("employee_name", "").astype(str),
        "amount": 0.0,
        "net_amount": 0.0,
        "signed_amount": 0.0,
        "source": "hours",
        "anomaly_flags": "",
        "license_num": pd.NA,
        "tool_name": _col("employee_name", ""),
        "work_hours": _col("total_hours", 0.0),
    })
    rows = rows[rows["month"].notna()]
    for col in MASTER_SCHEMA_COLS:
        if col not in rows.columns:
            rows[col] = pd.NA
    return rows[MASTER_SCHEMA_COLS].reset_index(drop=True)


def load_balance_snapshots(project_id: str) -> pd.DataFrame:
    """מחזיר את תצלומי המאזן של הפרויקט (לבקרה — לא תנועות)."""
    return balance_store.load_snapshots(project_id)


def build_master() -> pd.DataFrame:
    """בונה מאסטר מלא של כל הפרויקטים × כל החודשים, שומר ל-parquet.

    לכל פרויקט: אם קיים מאגר תנועות מצטבר (ledger_store) — הכרטסת
    נלקחת ממנו והחודש נגזר מתאריך התנועה; אחרת נשמרת התנהגות הקבצים
    לפי-חודש. סולר/שעות/מאזן-מלאי תמיד נטענים מקבצי החודש.

    Returns:
        ה-DataFrame המלא (גם נשמר ל-data/master.parquet).
    """
    tools = _load_tools_registry()
    all_rows: list[pd.DataFrame] = []

    # כש-Neon מוגדר, ההזנות הידניות נקראות *חי* מ-Neon ע"י load_master_merged
    # ולכן אסור לאפות אותן ל-master.parquet — אחרת ייספרו פעמיים.
    neon_on = False
    try:
        from core import cloud_db
        neon_on = cloud_db.is_configured()
    except Exception:
        neon_on = False

    projects = list_available_projects()
    for proj in projects:
        project_id = proj["project_id"]
        project_name = proj.get("project_name", project_id)
        has_store = ledger_store.has_store(project_id)

        # הזנה ידנית (סולר/שעות) — נטענת פעם אחת לכל הפרויקט, מתפלגת לחודשים.
        # כש-Neon פעיל מדלגים על אפייה (הנתונים יתווספו חי מ-Neon).
        if neon_on:
            manual_solar = pd.DataFrame(columns=MASTER_SCHEMA_COLS)
            manual_hours = pd.DataFrame(columns=MASTER_SCHEMA_COLS)
        else:
            manual_solar = aggregate_manual_solar(project_id, project_name)
            manual_hours = aggregate_manual_hours(project_id, project_name)
        manual_all = pd.concat(
            [f for f in (manual_solar, manual_hours) if not f.empty],
            ignore_index=True, sort=False,
        ) if (not manual_solar.empty or not manual_hours.empty) else pd.DataFrame(columns=MASTER_SCHEMA_COLS)
        manual_months = (
            set(manual_all["month"].dropna().unique())
            if not manual_all.empty else set()
        )

        def _manual_for(month: str) -> pd.DataFrame:
            if manual_all.empty:
                return pd.DataFrame()
            return manual_all[manual_all["month"] == month]

        if has_store:
            # כרטסת מהמאגר המצטבר (כל החודשים בבת אחת, לפי תאריך תנועה)
            store_chash = aggregate_store_chashbashevet(project_id, project_name)
            store_months = (
                set(store_chash["month"].dropna().unique())
                if not store_chash.empty else set()
            )
            folder_months = set(list_available_months(project_id))
            for month in sorted(store_months | folder_months | manual_months):
                frames: list[pd.DataFrame] = []
                mc = store_chash[store_chash["month"] == month] if not store_chash.empty else pd.DataFrame()
                if not mc.empty:
                    frames.append(mc)
                if month in folder_months:
                    loaded = load_project_month(project_id, month)
                    other = aggregate_month(loaded, project_id, project_name, month,
                                            include_chashbashevet=False)
                    if not other.empty:
                        frames.append(other)
                man = _manual_for(month)
                if not man.empty:
                    frames.append(man)
                if not frames:
                    continue
                df = pd.concat(frames, ignore_index=True, sort=False)
                for col in MASTER_SCHEMA_COLS:
                    if col not in df.columns:
                        df[col] = pd.NA
                df = df[MASTER_SCHEMA_COLS]
                df = detect_anomalies(df, tools)
                all_rows.append(df)
                logger.info("Built %d rows (store) for %s/%s", len(df), project_id, month)
            continue

        # — נתיב קלאסי: קבצים לפי-חודש —
        folder_months = set(list_available_months(project_id))
        for month in sorted(folder_months | manual_months):
            frames = []
            if month in folder_months:
                loaded = load_project_month(project_id, month)
                fm = aggregate_month(loaded, project_id, project_name, month)
                if not fm.empty:
                    frames.append(fm)
            man = _manual_for(month)
            if not man.empty:
                frames.append(man)
            if not frames:
                continue
            df = pd.concat(frames, ignore_index=True, sort=False)
            for col in MASTER_SCHEMA_COLS:
                if col not in df.columns:
                    df[col] = pd.NA
            df = df[MASTER_SCHEMA_COLS]
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

    # Build fuel_invoices parquet
    try:
        build_fuel_invoices_parquet()
    except Exception as e:
        logger.exception("fuel_invoices parquet build failed (non-fatal): %s", e)

    # Build fuel_tracker parquet (data/projects/<id>/מעקב סולר וטיפולים*.xlsx)
    try:
        build_fuel_tracker_parquet()
    except Exception as e:
        logger.exception("fuel_tracker parquet build failed (non-fatal): %s", e)

    # Sync projects + suppliers mirrors (non-fatal)
    try:
        from core import control_db
        n_p = control_db.sync_projects_from_xlsx(PROJECTS_REGISTRY)
        n_s = control_db.sync_suppliers_from_master(master)
        logger.info("Synced %d projects, %d suppliers to control_db", n_p, n_s)
    except Exception as e:
        logger.exception("projects/suppliers sync failed (non-fatal): %s", e)

    return master


def load_master() -> pd.DataFrame:
    """טוען את master.parquet אם קיים. אחרת מחזיר DataFrame ריק עם הסכמה.

    משלים עמודות סכמה חסרות (parquet ישן שנבנה לפני הוספת עמודה חדשה,
    למשל document_date/value_date) כדי שצרכנים שמסתמכים עליהן לא יקרסו.
    """
    if MASTER_PARQUET.exists():
        try:
            df = pd.read_parquet(MASTER_PARQUET)
            for col in MASTER_SCHEMA_COLS:
                if col not in df.columns:
                    df[col] = pd.NaT if col in ("document_date", "value_date") else pd.NA
            return df
        except Exception as e:
            logger.exception("Failed to load master parquet: %s", e)
    return pd.DataFrame(columns=MASTER_SCHEMA_COLS)


def load_manual_neon_rows(project_id: str, project_name: str) -> pd.DataFrame:
    """טוען הזנות ידניות (סולר+שעות) מ-Neon וממיר לסכמת master.

    משמש את load_master_merged כדי להציג נתונים ידניים חיים מהענן
    מבלי לאפות אותם ל-master.parquet (מניעת כפילות).
    """
    from core import cloud_db
    frames: list[pd.DataFrame] = []
    try:
        solar_store = cloud_db.load_entries(project_id, "solar")
        s = aggregate_manual_solar(project_id, project_name, store=solar_store)
        if not s.empty:
            frames.append(s)
    except Exception as e:
        logger.warning("Neon solar load failed for %s: %s", project_id, e)
    try:
        hours_store = cloud_db.load_entries(project_id, "hours")
        h = aggregate_manual_hours(project_id, project_name, store=hours_store)
        if not h.empty:
            frames.append(h)
    except Exception as e:
        logger.warning("Neon hours load failed for %s: %s", project_id, e)
    if not frames:
        return pd.DataFrame(columns=MASTER_SCHEMA_COLS)
    return pd.concat(frames, ignore_index=True, sort=False)


def load_master_merged() -> pd.DataFrame:
    """master.parquet + הזנות ידניות חיות מ-Neon (אם מוגדר).

    כש-Neon לא מוגדר — מחזיר את master.parquet כמות שהוא (ההזנות הידניות
    כבר אפויות בו ע"י build_master). כש-Neon מוגדר — build_master דילג על
    אפיית ההזנות, והן מתווספות כאן עם סימון ``origin='neon_manual'`` כדי
    שלא ייספרו פעמיים.
    """
    m = load_master()
    try:
        from core import cloud_db
        if not cloud_db.is_configured():
            return m
    except Exception:
        return m

    neon_frames: list[pd.DataFrame] = []
    try:
        for proj in list_available_projects():
            pid = proj["project_id"]
            pname = proj.get("project_name", pid)
            rows = load_manual_neon_rows(pid, pname)
            if not rows.empty:
                neon_frames.append(rows)
    except Exception as e:
        logger.warning("load_master_merged: Neon merge failed: %s", e)
        return m

    if not neon_frames:
        return m
    nm = pd.concat(neon_frames, ignore_index=True, sort=False)
    nm["origin"] = "neon_manual"  # סימון ברור — נתון ידני מהענן
    merged = pd.concat([m, nm], ignore_index=True, sort=False)
    # ייצוב dtype: ה-concat עלול לשדרג עמודות כסף ל-object (שורות Neon
    # חסרות net_amount/signed_amount). מכריחים חזרה ל-float כדי שחישובי
    # .round()/סטטיסטיקה בטאבים לא יקרסו (באג ה-TypeError בטאב בקרת איכות).
    return coerce_master_numeric(merged)


def verify_manual_persisted(project_id: str, kind: str,
                            months: list[str]) -> dict:
    """אימות שההזנות הידניות נשמרו לצמיתות — Neon אם מוגדר, אחרת master.parquet.

    מחזיר את אותו מבנה כמו verify_manual_in_master:
    {"rows_in_master": int, "months_found": [...], "ok": bool}.
    """
    try:
        from core import cloud_db
        if cloud_db.is_configured():
            return cloud_db.verify(project_id, kind, months)
    except Exception as e:
        logger.warning("Neon verify failed, fallback to master.parquet: %s", e)
    return verify_manual_in_master(project_id, kind, months)


def _verify_manual_in_store(project_id: str, kind: str,
                            months: list[str]) -> dict:
    """אימות מקומי לסוגים שאינם ב-master (כלים/ניצול) — קריאה חוזרת מהמאגר.

    סופר את שורות המאגר (parquet) לפי חודש ובודק שכל חודש שנשמר נמצא.
    """
    result = {"rows_in_master": 0, "months_found": [], "ok": False}
    try:
        store = manual_store.load_store(project_id, kind)
    except Exception as e:
        logger.exception("_verify_manual_in_store load failed: %s", e)
        return result
    if store is None or store.empty or "month" not in store.columns:
        return result
    found = sorted(store["month"].dropna().astype(str).unique().tolist())
    result["rows_in_master"] = int(len(store))
    result["months_found"] = found
    result["ok"] = bool(months) and all(mo in found for mo in months)
    return result


def verify_manual_in_master(project_id: str, kind: str,
                            months: list[str]) -> dict:
    """אימות שהנתונים הידניים אכן הגיעו ל-master.parquet (קריאה מהדיסק).

    קורא מחדש את master.parquet מהדיסק (לא מהקאש), ומספר את שורות
    ה-source הרלוונטי (solar/hours) לפרויקט בחודשים שנשמרו.

    מחזיר: {"rows_in_master": int, "months_found": [..], "ok": bool}
    """
    # סוגים שאינם זורמים ל-master (כלים/ניצול דלק) — אימות מול המאגר עצמו.
    if not manual_store.flows_to_master(kind):
        return _verify_manual_in_store(project_id, kind, months)

    source = "solar" if kind == "solar" else "hours"
    result = {"rows_in_master": 0, "months_found": [], "ok": False}
    if not MASTER_PARQUET.exists():
        return result
    try:
        m = pd.read_parquet(MASTER_PARQUET)
    except Exception as e:
        logger.exception("verify_manual_in_master read failed: %s", e)
        return result
    if m.empty or "source" not in m.columns:
        return result
    sel = (m["project_id"] == project_id) & (m["source"] == source)
    if months:
        sel &= m["month"].isin(months)
    sub = m[sel]
    result["rows_in_master"] = int(len(sub))
    result["months_found"] = sorted(sub["month"].dropna().unique().tolist())
    # תקין אם נמצאו שורות בכל חודש שנשמר
    result["ok"] = bool(months) and all(mo in result["months_found"] for mo in months)
    return result


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
