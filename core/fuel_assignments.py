"""שיוך ידני של תנועות דלק לכלים — שכבת persistence.

מקור הבעיה: התאמה אוטומטית (equipment_matcher) לא תופסת הכל. כשהמשתמש
משייך ידנית תנועה מסוימת לכלי מסוים, אנחנו רוצים לשמור את הקביעה
הזאת כדי שלא תאבד בריענון או בבניית מאסטר מחדש.

מפתח השיוך: stable hash של (date, supplier, amount, description) של
התנועה. SHA1 מקצרים ל-16 תווים — מספיק לצורך מפתח.

קובץ: data/projects/<project_id>/fuel_assignments.json
פורמט: { "<row_hash>": {"license_num": int, "assigned_at": iso,
                          "notes": str} }
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


PROJECTS_DIR = Path(__file__).resolve().parent.parent / "data" / "projects"


def _file(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "fuel_assignments.json"


def row_hash(date, supplier, amount, description) -> str:
    """Hash יציב לזיהוי שורת דלק.

    הקלט מומר ל-string ומחושב SHA1 → 16 תווים ראשונים.
    גם NaN/None נטופלו → נציג כ-'' כדי שאותה שורה תיתן אותו hash תמיד.
    """
    def _n(v):
        if v is None:
            return ""
        try:
            if pd.isna(v):
                return ""
        except (TypeError, ValueError):
            pass
        if isinstance(v, (pd.Timestamp, datetime)):
            return v.strftime("%Y-%m-%d")
        return str(v).strip()

    key = "|".join([_n(date), _n(supplier),
                     f"{float(_n(amount) or 0):.2f}", _n(description)])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _load_all(project_id: str) -> dict:
    p = _file(project_id)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        logger.warning("Failed to load fuel_assignments for %s: %s",
                        project_id, e)
        return {}


def _save_all(project_id: str, data: dict) -> None:
    p = _file(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def assign(project_id: str, row_hash_value: str, license_num: int,
           notes: str = "") -> None:
    """שומר שיוך ידני של שורה ספציפית לכלי."""
    data = _load_all(project_id)
    data[row_hash_value] = {
        "license_num": int(license_num),
        "assigned_at": datetime.now().isoformat(timespec="seconds"),
        "notes": (notes or "").strip(),
    }
    _save_all(project_id, data)


def unassign(project_id: str, row_hash_value: str) -> None:
    """מסיר שיוך ידני."""
    data = _load_all(project_id)
    if row_hash_value in data:
        del data[row_hash_value]
        _save_all(project_id, data)


def get_assignment(project_id: str, row_hash_value: str) -> int | None:
    """מחזיר license_num שמשויך ידנית, או None."""
    data = _load_all(project_id)
    rec = data.get(row_hash_value)
    return int(rec["license_num"]) if rec and "license_num" in rec else None


def list_assignments(project_id: str) -> pd.DataFrame:
    """מחזיר DataFrame של כל השיוכים הידניים בפרויקט."""
    data = _load_all(project_id)
    if not data:
        return pd.DataFrame(columns=["row_hash", "license_num",
                                       "assigned_at", "notes"])
    rows = []
    for h, rec in data.items():
        rows.append({
            "row_hash": h,
            "license_num": rec.get("license_num"),
            "assigned_at": rec.get("assigned_at", ""),
            "notes": rec.get("notes", ""),
        })
    return pd.DataFrame(rows)


def fuel_cost_per_license(project_id: str,
                            df_master: pd.DataFrame) -> pd.DataFrame:
    """מחזיר DataFrame של עלות דלק מ-chashbashevet שמשויכת ידנית
    לכל license_num.

    שימושי ל-tab "פעילות כלים" כדי להראות את העלות הכספית של חיובי
    הסולר המצטברים שהוקצו ידנית לכלי ספציפי.

    Returns:
        DataFrame עם עמודות: license_num, assigned_fuel_cost,
        n_assigned_tx.
    """
    cols = ["license_num", "assigned_fuel_cost", "n_assigned_tx"]
    assignments = _load_all(project_id)
    if not assignments or df_master.empty:
        return pd.DataFrame(columns=cols)

    # סורק את שורות chashbashevet, מחשב hash, ומסנן רק את אלו שיש להן שיוך
    chash = df_master[df_master["source"] == "chashbashevet"] \
        if "source" in df_master.columns else df_master
    if chash.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for _, r in chash.iterrows():
        h = row_hash(r.get("date"), r.get("supplier"),
                      r.get("amount"), r.get("description"))
        if h in assignments:
            rows.append({
                "license_num": int(assignments[h]["license_num"]),
                "amount": float(r.get("amount", 0) or 0),
            })

    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    agg = df.groupby("license_num").agg(
        assigned_fuel_cost=("amount", "sum"),
        n_assigned_tx=("amount", "size"),
    ).reset_index()
    return agg


def apply_to_enriched(enriched_df: pd.DataFrame, project_id: str,
                       equipment_df: pd.DataFrame) -> pd.DataFrame:
    """מחיל שיוכים ידניים על DataFrame של תנועות דלק שכבר עברו matching.

    Override של auto-match: אם יש שיוך ידני, השיוך גובר.
    מוסיף עמודה _manual_override (True / False).
    """
    if enriched_df.empty:
        out = enriched_df.copy()
        out["_manual_override"] = False
        return out

    assignments = _load_all(project_id)
    if not assignments:
        out = enriched_df.copy()
        out["_manual_override"] = False
        return out

    # אינדוקס כלי לפי license_num — לקבל tool_name וכו'
    eq_idx = equipment_df.set_index("license_num", drop=False) \
        if not equipment_df.empty and "license_num" in equipment_df.columns \
        else pd.DataFrame()

    out = enriched_df.copy().reset_index(drop=True)
    out["_manual_override"] = False
    for i, row in out.iterrows():
        h = row_hash(row.get("date"), row.get("supplier"),
                      row.get("total_cost") or row.get("amount"),
                      row.get("description"))
        if h in assignments:
            lic = int(assignments[h]["license_num"])
            out.at[i, "matched_license_num"] = lic
            out.at[i, "matched_by"] = "manual"
            out.at[i, "match_confidence"] = "manual"
            out.at[i, "match_note"] = "שיוך ידני"
            out.at[i, "_manual_override"] = True
            # תיוג tool_name + equipment_group מתוך הרשימה
            if not eq_idx.empty and lic in eq_idx.index:
                eq_row = eq_idx.loc[lic]
                if isinstance(eq_row, pd.DataFrame):
                    eq_row = eq_row.iloc[0]
                out.at[i, "matched_tool_name"] = str(eq_row.get("tool_name", ""))
                out.at[i, "equipment_group"] = str(eq_row.get("equipment_group") or "")

    return out
