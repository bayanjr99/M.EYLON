"""שכבת AI - Wrapper דק ל-Anthropic SDK עבור שאילתות ביקורת.

דורש משתנה סביבה ANTHROPIC_API_KEY (טוען מ-.env אם קיים).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 2000
SYSTEM_PROMPT_DEFAULT = (
    "אתה עוזר ביקורת פנימית בחברת בנייה ישראלית. "
    "אתה מנתח דוחות חשבונאיים, צריכת סולר, ושעות כלים. "
    "תענה בעברית, ברור וקצר. "
    "תתמקד בזיהוי חריגות וסיכונים פיננסיים."
)


def _get_client() -> anthropic.Anthropic | None:
    """מחזיר client של Anthropic אם API key קיים, אחרת None."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
        return None
    return anthropic.Anthropic(api_key=api_key)


def ask_ai_about_data(
    df: pd.DataFrame,
    question: str,
    context: str = "",
    model: str = DEFAULT_MODEL,
) -> str:
    """שאלה חופשית על דאטה-פריים. החזרת תשובה בעברית.

    Args:
        df: הדאטה לניתוח (יומר ל-string).
        question: שאלת המשתמש בעברית.
        context: הקשר נוסף (סטטיסטיקות, פילטרים פעילים וכו').
        model: שם המודל. ברירת מחדל - Haiku 4.5.

    Returns:
        תשובה בעברית, או הודעת שגיאה.
    """
    client = _get_client()
    if client is None:
        return "אין מפתח API. הגדר ANTHROPIC_API_KEY בקובץ .env"

    # לחתוך את הטבלה אם גדולה מדי
    df_str = df.head(200).to_string(index=False) if len(df) > 200 else df.to_string(index=False)

    prompt = f"""יש לי את הנתונים הבאים מדשבורד הביקורת:

{context}

טבלה (עד 200 שורות ראשונות):
{df_str}

שאלת המשתמש:
{question}

תענה בעברית, ברור וקצר. אם רלוונטי - הזכר מספרים ספציפיים מהטבלה."""

    try:
        res = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT_DEFAULT,
            messages=[{"role": "user", "content": prompt}],
        )
        return res.content[0].text.strip()
    except Exception as e:
        logger.exception("AI request failed")
        return f"שגיאה ב-AI: {e}"


def detect_issues_with_ai(df: pd.DataFrame, model: str = DEFAULT_MODEL) -> list[dict[str, Any]]:
    """מבקש מה-AI לזהות חריגות בדאטה ולהחזיר JSON מובנה.

    Returns:
        רשימת חריגות, כל אחת dict עם המפתחות:
        project, category, supplier, issue_type, details, recommendation.
        אם אין חריגות או חל error - מחזיר רשימה ריקה.
    """
    client = _get_client()
    if client is None:
        return []

    df_str = df.head(200).to_string(index=False) if len(df) > 200 else df.to_string(index=False)

    prompt = f"""אתה מנתח דוח ביקורת פנימית מחברת בנייה. הנה הנתונים:

{df_str}

תחזיר JSON בלבד, בלי שום טקסט נוסף, בפורמט:
[
  {{
    "project": "",
    "category": "",
    "supplier": "",
    "issue_type": "",
    "details": "",
    "recommendation": ""
  }}
]

אם אין חריגות תחזיר [] בלבד.

תזהה:
- צריכת סולר חריגה (ליטר/שעה גבוה מהתקן)
- תדלוקים ללא שעות עבודה
- חיובים חריגים מספק יחיד
- חודש עם זינוק לא מוסבר
- סכומים גדולים מאוד
- כפילויות חשודות
- מילות מפתח כמו "תיקון", "טעות", "לבטל"
"""

    try:
        res = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system="Return only valid JSON. No markdown. No explanation.",
            messages=[{"role": "user", "content": prompt}],
        )
        txt = res.content[0].text.strip()
        if "```" in txt:
            parts = txt.split("```")
            if len(parts) > 1:
                txt = parts[1]
                if txt.startswith("json"):
                    txt = txt[4:]
        txt = txt.strip()
        start = txt.find("[")
        end = txt.rfind("]") + 1
        if start != -1 and end != 0:
            txt = txt[start:end]
        return json.loads(txt)
    except Exception:
        logger.exception("AI issue detection failed")
        return []


def summarize_month(df: pd.DataFrame, project_name: str, month: str, model: str = DEFAULT_MODEL) -> str:
    """מייצר סיכום חופשי של חודש בודד בפרויקט."""
    client = _get_client()
    if client is None:
        return "אין מפתח API. הגדר ANTHROPIC_API_KEY בקובץ .env"

    df_str = df.head(150).to_string(index=False) if len(df) > 150 else df.to_string(index=False)

    prompt = f"""סכם את הפעילות בפרויקט "{project_name}" בחודש {month}:

{df_str}

תכתוב פסקה אחת קצרה: סה"כ הוצאות, ספק עיקרי, קטגוריה דומיננטית,
חריגות אם זוהו. סגנון מקצועי וקצר."""

    try:
        res = client.messages.create(
            model=model,
            max_tokens=800,
            system=SYSTEM_PROMPT_DEFAULT,
            messages=[{"role": "user", "content": prompt}],
        )
        return res.content[0].text.strip()
    except Exception as e:
        logger.exception("AI summary failed")
        return f"שגיאה ב-AI: {e}"
