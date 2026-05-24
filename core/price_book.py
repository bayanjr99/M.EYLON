"""ניהול מחירון פרויקט (price_book.xlsx).

הקובץ מכיל מחירי יחידה מוסכמים לפרויקט - מאפשר השוואה בין
מחיר חוזי למחיר בפועל בחשבוניות.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def load_price_book(file_path: str | Path) -> pd.DataFrame:
    """טוען מחירון פרויקט מ-XLSX.

    Returns:
        DataFrame עם עמודות: item_code, item_name, unit,
        unit_price, supplier (אופציונלי), notes (אופציונלי).
    """
    raise NotImplementedError("Stub - יש למלא בשלב הבא")


def lookup_price(price_book: pd.DataFrame, item_name: str) -> float | None:
    """מחפש מחיר יחידה לפי שם פריט (חיפוש רך).

    Returns:
        מחיר היחידה אם נמצא, None אחרת.
    """
    raise NotImplementedError
