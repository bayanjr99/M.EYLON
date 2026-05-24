"""נרמול טקסט עברי / מעורב להשוואה ומציאת התאמות.

מקור: מבוסס על utils/hebrew.py של מערכת billing_system.
"""
import re
import unicodedata


# ── תבניות נרמול אגרסיביות ──────────────────────────────────────
_LEGAL_RE = re.compile(
    r"""\s*\(?(?:בע["״"]מ|בעמ|בע'מ|ltd\.?|limited)\)?"""
    r"|\s*\(\d{4}\)"
    r"|\s*חב'\s*"
    r"|\s*ושות'\s*"
    r"|\s*-\s*$",
    re.IGNORECASE,
)
_DOUBLE_YOD = re.compile("יי")
_GERESH = re.compile('[״""]')


def normalize(text: str) -> str:
    """נרמול קל: הסרת ניקוד, כיווץ רווחים, lowercase.

    מתאים להשוואה רכה בין מחרוזות. שומר סיומות משפטיות וסימני פיסוק.
    """
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def match_normalize(text: str) -> str:
    """נרמול אגרסיבי להתאמת שמות חברות/ספקים/אתרים.

    בנוסף ל-normalize:
      • מסיר סיומות משפטיות (בע"מ, בעמ, Ltd.)
      • מצמצם יי כפול → י
      • מסיר סימני פיסוק (" ' ( ) - . ׳)
      • מסיר מספרים בודדים (לדוגמה "(2024)")
    """
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _GERESH.sub('"', s)
    s = _LEGAL_RE.sub(" ", s)
    s = re.sub(r"""["'()\-.׳]""", " ", s)
    s = _DOUBLE_YOD.sub("י", s)
    s = re.sub(r"\b\d+\b", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def token_set(text: str) -> set[str]:
    """ממיר טקסט למילים נורמלות (set)."""
    return set(normalize(text).split())


def similarity(a: str, b: str) -> float:
    """מקדם חפיפת טוקנים [0, 1]: |A∩B| / max(|A|, |B|).

    הערה: לא Jaccard (שמחלק בחיתוך). הבחירה ב-max מאפשרת התאמה
    גם כשמחרוזת אחת קצרה משמעותית מהשנייה.
    """
    sa, sb = token_set(a), token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def contains(needle: str, haystack: str) -> bool:
    """True אם כל הטוקנים ב-needle מופיעים ב-haystack."""
    sn = token_set(needle)
    return bool(sn) and sn.issubset(token_set(haystack))
