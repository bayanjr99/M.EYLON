"""אגרגציה של נתוני פרויקט לתצוגות שונות.

מקבל את ה-master.parquet ומחזיר תצוגות אגרגטיביות לפי:
    project / month / category / supplier / tool / כל שילוב.

הערה לסימן: בכל המאסטר amount > 0 = הוצאה, amount < 0 = הכנסה.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _expenses_only(df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר רק שורות הוצאה (amount חיובי)."""
    if df.empty:
        return df
    return df[df["amount"] > 0]


def _income_only(df: pd.DataFrame) -> pd.DataFrame:
    """מחזיר רק שורות הכנסה (amount שלילי)."""
    if df.empty:
        return df
    return df[df["amount"] < 0]


def by_project(df: pd.DataFrame) -> pd.DataFrame:
    """סיכום הוצאות לפי פרויקט.

    Returns:
        DataFrame עם: project_id, project_name, total_expenses,
        total_income, balance, num_transactions.
    """
    cols = ["project_id", "project_name", "total_expenses",
            "total_income", "balance", "num_transactions"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    grouped = df.groupby(["project_id", "project_name"], dropna=False).agg(
        total_expenses=("amount", lambda s: s[s > 0].sum()),
        total_income=("amount", lambda s: -s[s < 0].sum()),
        num_transactions=("amount", "count"),
    ).reset_index()
    grouped["balance"] = grouped["total_income"] - grouped["total_expenses"]
    return grouped[cols].sort_values("total_expenses", ascending=False)


def by_month(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """סיכום הוצאות לפי חודש (אופציונלית לפרויקט בודד)."""
    cols = ["month", "total_expenses", "total_income", "balance", "num_transactions"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = df if project_id is None else df[df["project_id"] == project_id]
    if data.empty:
        return pd.DataFrame(columns=cols)

    grouped = data.groupby("month", dropna=False).agg(
        total_expenses=("amount", lambda s: s[s > 0].sum()),
        total_income=("amount", lambda s: -s[s < 0].sum()),
        num_transactions=("amount", "count"),
    ).reset_index()
    grouped["balance"] = grouped["total_income"] - grouped["total_expenses"]
    grouped = grouped.sort_values("month").reset_index(drop=True)
    return grouped[cols]


def by_category(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """סיכום הוצאות לפי קטגוריה."""
    cols = ["category", "total_amount", "num_transactions", "share_pct"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = df if project_id is None else df[df["project_id"] == project_id]
    data = _expenses_only(data)
    if data.empty:
        return pd.DataFrame(columns=cols)

    grouped = data.groupby("category", dropna=False).agg(
        total_amount=("amount", "sum"),
        num_transactions=("amount", "count"),
    ).reset_index()
    total = grouped["total_amount"].sum()
    grouped["share_pct"] = (grouped["total_amount"] / total * 100).round(1) if total else 0.0
    grouped = grouped.sort_values("total_amount", ascending=False).reset_index(drop=True)
    return grouped[cols]


def by_supplier(df: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """Top N ספקים לפי סה"כ חיובים, על פני כל הפרויקטים."""
    cols = ["supplier", "total_amount", "num_transactions",
            "num_projects", "first_date", "last_date"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = _expenses_only(df)
    data = data[data["supplier"].notna() & (data["supplier"] != "")]
    if data.empty:
        return pd.DataFrame(columns=cols)

    grouped = data.groupby("supplier", dropna=False).agg(
        total_amount=("amount", "sum"),
        num_transactions=("amount", "count"),
        num_projects=("project_id", "nunique"),
        first_date=("date", "min"),
        last_date=("date", "max"),
    ).reset_index()
    grouped = grouped.sort_values("total_amount", ascending=False).head(top_n).reset_index(drop=True)
    return grouped[cols]


def suppliers_categorized(df: pd.DataFrame, top_n: int = 100) -> pd.DataFrame:
    """ספקים עם הקטגוריה הדומיננטית שלהם (לפי הסכום הכי גדול).

    Returns DataFrame עם: supplier, primary_category, total_amount,
    num_transactions, num_categories, secondary_categories.
    """
    cols = ["supplier", "primary_category", "total_amount", "num_transactions",
            "num_categories", "secondary_categories"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    data = _expenses_only(df)
    data = data[data["supplier"].notna() & (data["supplier"] != "")]
    if data.empty:
        return pd.DataFrame(columns=cols)

    # Per (supplier, category) sum
    sc = data.groupby(["supplier", "category"])["amount"].sum().reset_index()

    rows = []
    for sup, grp in sc.groupby("supplier"):
        grp_sorted = grp.sort_values("amount", ascending=False)
        primary = grp_sorted.iloc[0]["category"]
        total = float(grp["amount"].sum())
        n_cats = len(grp)
        secondary = grp_sorted.iloc[1:]["category"].tolist() if n_cats > 1 else []
        n_tx = int(data[data["supplier"] == sup].shape[0])
        rows.append({
            "supplier": sup,
            "primary_category": primary,
            "total_amount": round(total, 0),
            "num_transactions": n_tx,
            "num_categories": n_cats,
            "secondary_categories": ", ".join(secondary[:3]) if secondary else "",
        })

    out = pd.DataFrame(rows, columns=cols).sort_values("total_amount", ascending=False)
    return out.head(top_n)


def suppliers_by_category(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """מחזיר dict: category → DataFrame של ספקים בקטגוריה.

    שימושי להצגת tab/section נפרד לכל קטגוריה.
    """
    cat_df = suppliers_categorized(df, top_n=10_000)
    if cat_df.empty:
        return {}
    return {cat: grp.reset_index(drop=True)
            for cat, grp in cat_df.groupby("primary_category")}


def supplier_month_matrix(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """מטריצת ספק × חודש (pivot)."""
    if df.empty:
        return pd.DataFrame()

    data = _expenses_only(df)
    data = data[data["supplier"].notna() & (data["supplier"] != "")]
    if data.empty:
        return pd.DataFrame()

    top_suppliers = (
        data.groupby("supplier")["amount"].sum()
            .sort_values(ascending=False)
            .head(top_n)
            .index
    )
    data = data[data["supplier"].isin(top_suppliers)]
    pivot = data.pivot_table(
        index="supplier", columns="month", values="amount",
        aggfunc="sum", fill_value=0,
    )
    pivot = pivot.reindex(top_suppliers)
    pivot["סה\"כ"] = pivot.sum(axis=1)
    return pivot.sort_values("סה\"כ", ascending=False)


def project_summary(df: pd.DataFrame, project_id: str) -> dict:
    """מחזיר סיכום KPI לפרויקט בודד.

    שותף בין כרטיס בדף הראשי לטאב הסקירה בדף הפרויקט.

    Returns:
        dict עם: revenue, expenses, profit, profit_pct, num_transactions,
        num_suppliers, num_tools, num_anomalies, has_data, months, first_date, last_date.
    """
    summary = {
        "revenue": 0.0,
        "expenses": 0.0,
        "profit": 0.0,
        "profit_pct": 0.0,
        "num_transactions": 0,
        "num_suppliers": 0,
        "num_tools": 0,
        "num_anomalies": 0,
        "has_data": False,
        "months": [],
        "first_date": None,
        "last_date": None,
    }
    if df.empty or "project_id" not in df.columns:
        return summary

    data = df[df["project_id"] == project_id]
    if data.empty:
        return summary

    summary["has_data"] = True
    summary["num_transactions"] = int(len(data))

    if "amount" in data.columns:
        # סינון מרכזי דרך real_income_mask — מקור אמת יחיד למה נספר
        # כהכנסה (חיוב ספק / פרויקט), כדי שערכי KPI יהיו זהים בין כל
        # המסכים (סקירה, רשימת פרויקטים, טאב כספים).
        from core.chashbashevet_loader import real_income_mask
        chash = data[data["source"] == "chashbashevet"] if "source" in data.columns else data
        income_mask = real_income_mask(chash)
        income_rows = chash[income_mask]
        expense_rows = chash[~income_mask]

        # הכנסה: amount שלילי אחרי inversion ב-loader. revenue = abs(sum)
        summary["revenue"] = float(-income_rows["amount"].sum()) if not income_rows.empty else 0.0
        # הוצאות: amount > 0 מחשבונות שאינם הכנסה
        summary["expenses"] = float(expense_rows.loc[expense_rows["amount"] > 0, "amount"].sum()) \
            if not expense_rows.empty else 0.0
        summary["profit"] = summary["revenue"] - summary["expenses"]
        if summary["revenue"] > 0:
            summary["profit_pct"] = (summary["profit"] / summary["revenue"]) * 100

    if "supplier" in data.columns:
        summary["num_suppliers"] = int(data["supplier"].dropna().replace("", pd.NA).dropna().nunique())
    if "license_num" in data.columns:
        summary["num_tools"] = int(data["license_num"].dropna().nunique())
    if "anomaly_flags" in data.columns:
        summary["num_anomalies"] = int(
            data["anomaly_flags"].astype(str).str.len().gt(2).sum()
        )
    if "month" in data.columns:
        months = sorted(data["month"].dropna().unique().tolist())
        summary["months"] = months
    if "date" in data.columns:
        dates = pd.to_datetime(data["date"], errors="coerce").dropna()
        if not dates.empty:
            summary["first_date"] = dates.min()
            summary["last_date"] = dates.max()

    return summary


def category_month_matrix(df: pd.DataFrame, project_id: str | None = None) -> pd.DataFrame:
    """מטריצת קטגוריה × חודש (pivot)."""
    if df.empty:
        return pd.DataFrame()

    data = df if project_id is None else df[df["project_id"] == project_id]
    data = _expenses_only(data)
    if data.empty:
        return pd.DataFrame()

    pivot = data.pivot_table(
        index="category", columns="month", values="amount",
        aggfunc="sum", fill_value=0,
    )
    pivot["סה\"כ"] = pivot.sum(axis=1)
    return pivot.sort_values("סה\"כ", ascending=False)
