"""טעינת חשבוניות ספקים (Placeholder - שלב עתידי).

המבנה ייקבע כשיתקבלו דוגמאות אמיתיות. כרגע מספק חתימה
ריקה לצורך אחידות הארכיטקטורה.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def load_invoices(file_path: str | Path) -> pd.DataFrame:
    """טוען חשבוניות ספקים. ייושם בשלב מאוחר יותר.

    Returns:
        DataFrame ריק עם הסכמה: date, supplier, invoice_num,
        amount, description, project_id.
    """
    raise NotImplementedError("Placeholder - לא ממומש עדיין")
