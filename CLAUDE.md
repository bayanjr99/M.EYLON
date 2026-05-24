# CLAUDE.md

מדריך זה מסביר ל-Claude Code את ארכיטקטורת מערכת הביקורת. לכל שינוי - קרא קודם את הקובץ הרלוונטי במלואו.

## מטרת המערכת

ביקורת פנימית של הוצאות פרויקטי בנייה בחברת מ. אילון אביב נכסים בע"מ. משתמש יחיד (המפתח), פועלת מקומית על Windows. לא ענן, לא login, לא multi-tenant.

## מבנה הפרויקט

```
construction_audit_system/
├── core/
│   ├── chashbashevet_loader.py   ← קריאת כרטיס הנהלה (XLSX → DataFrame מנורמל)
│   ├── solar_loader.py           ← קריאת דוח תדלוק, סינון לפי שם פרויקט
│   ├── hours_loader.py           ← קריאת דוח שעות כלים, סינון שורות פגומות
│   ├── invoice_loader.py         ← Placeholder לחשבוניות (שלב עתידי)
│   ├── price_book.py             ← מחירון פרויקט (לקריאה בלבד)
│   ├── categorizer.py            ← סיווג חשבונות לקטגוריות + fallback לפי טווח
│   ├── project_aggregator.py     ← Pivots: by_project / by_month / by_category / by_supplier
│   ├── anomaly_detector.py       ← 5 בדיקות חריגות - הלב של המערכת
│   ├── analytics.py              ← KPIs, מגמות חודשיות, Top-N
│   └── ai_insights.py            ← Wrapper גבוה-רמה מעל ai_tools
├── utils/
│   └── hebrew.py                 ← normalize, match_normalize, similarity, contains
├── scripts/
│   └── seed_reference_data.py    ← מייצר את 3 קבצי ה-XLSX של data/
├── data/
│   ├── projects_registry.xlsx    ← רשימת פרויקטים פעילים
│   ├── category_mapping.xlsx     ← מיפוי חשבון → קטגוריה
│   ├── tools_registry.xlsx       ← רשימת כלים + תקני סולר
│   ├── projects/
│   │   └── <project_id>/
│   │       ├── price_book.xlsx
│   │       └── <MM-YYYY>/
│   │           ├── chashbashevet.xlsx
│   │           ├── solar.xlsx
│   │           └── hours.xlsx
│   └── master.parquet            ← נוצר ע"י pipeline.build_master()
├── output/
│   ├── cache/
│   └── reports/
├── app.py                        ← Streamlit dashboard (port 8501), 6 טאבים
├── pipeline.py                   ← אורקסטרציה: load → aggregate → detect → master
├── ai_tools.py                   ← Anthropic SDK wrapper (Haiku 4.5)
├── requirements.txt
├── start.bat / start.sh
├── .streamlit/config.toml
└── .gitignore                    ← data/projects/, master.parquet, output/, .env
```

## זרימת הנתונים

```
chashbashevet.xlsx ─┐
solar.xlsx ─────────┼─→ pipeline.load_project_month()
hours.xlsx ─────────┘         │
                              ▼
                     pipeline.aggregate_month()  ← categorizer.categorize()
                              │
                              ▼
                     pipeline.detect_anomalies() ← anomaly_detector.run_all_checks()
                              │
                              ▼
                       master.parquet
                              │
                              ▼
                          app.py (Streamlit)
```

`build_master()` רץ על כל הפרויקטים × כל החודשים. `run_month()` הוא קיצור דרך לחודש בודד.

## סכמת master.parquet

עמודות חובה: `project_id, project_name, month, date, category, subcategory, account_num, account_name, supplier, description, amount, source, anomaly_flags`.

עמודות אופציונליות (NaN לרשומות שלא רלוונטיות): `license_num, tool_name, liters, engine_hours, work_hours`.

- `source` ∈ {"chashbashevet", "solar", "hours", "manual"}
- `amount` חיובי להוצאות, שלילי להכנסות (חשבונות 927/951/7367).
- `anomaly_flags` - JSON string של רשימת flags, או "" אם תקין.

## קונבנציות

- **שמות משתנים באנגלית**, שמות עמודות בקבצי קלט בעברית (יש להמיר ב-loader).
- **type hints** בכל פונקציה (Python 3.10+).
- **docstring בעברית** בכל public function.
- **logging.getLogger(__name__)** במקום print.
- **קבועים בראש הקובץ** (PRICE_PER_LITER_NIS, INCOME_ACCOUNTS וכו').
- **השוואת מחרוזות עברית** - תמיד דרך `utils.hebrew` (normalize / match_normalize / similarity / contains). אסור `==` או `.lower()` ישיר.
- **error handling** ב-loaders - אסור לזרוק exception על קובץ פגום, יש לרשום warning ולהמשיך.
- כל קובץ < 500 שורות, אחרת לפצל.

## מה כבר ממומש (שלב 1 - השלד)

- ✓ מבנה תיקיות מלא
- ✓ קבצי config (requirements, .streamlit, .gitignore, start scripts)
- ✓ `utils/hebrew.py` - מלא ופונקציונלי
- ✓ `ai_tools.py` - מלא ופונקציונלי (3 פונקציות: ask, detect, summarize)
- ✓ `pipeline.list_available_projects()` ו-`list_available_months()` - מלא
- ✓ `pipeline.load_master()` - מלא
- ✓ `app.py` - שלד עם 6 טאבים, RTL CSS, sidebar עובד
- ✓ `scripts/seed_reference_data.py` - מייצר את 3 קבצי ה-XLSX

## מה עוד צריך לממש (שלב 2)

כל הפונקציות עם `raise NotImplementedError`:

1. **core/chashbashevet_loader.load_chashbashevet()** - הלב של המערכת. סורק שורה-שורה, מזהה כותרות חשבון מול שורות תנועה.
2. **core/solar_loader.load_solar()** - קריאת XLSX + סינון לפי `site_name` עם `utils.hebrew.contains`.
3. **core/hours_loader.load_hours()** - איתור הגליון הנכון + סינון שורות פגומות (work_hours < 0 או > 16).
4. **core/categorizer.{load_category_mapping, categorize}**
5. **core/project_aggregator.*** - כל ה-Pivots.
6. **core/anomaly_detector.*** - 5 הבדיקות.
7. **core/analytics.*** - KPIs.
8. **core/ai_insights.*** - הזרקת context אוטומטית לפני קריאה ל-ai_tools.
9. **pipeline.{load_project_month, aggregate_month, detect_anomalies, build_master, run_month}**
10. **app.py** - להחליף את ה-placeholders בקריאות אמיתיות לפונקציות.

## נקודות שדורשות תשומת לב מיוחדת

### solar.xlsx הוא מולטי-פרויקטי

הקובץ מכיל תדלוקים מכל הפרויקטים. החובה לסנן לפי `site_name` מ-`projects_registry.xlsx`. ההשוואה רכה (כי שם האתר ב-Pointer לא תמיד זהה למה שב-Registry). השתמש ב-`utils.hebrew.contains()`.

### hours.xlsx משתנה בין קבצים

יש קבצים שבהם הגליון נקרא "שעות עבודה כלים", יש "שעות עבודה". `hours_loader.HOURS_SHEET_NAMES` מנסה כמה אופציות. אם הגיע קובץ חדש עם שם גליון לא מוכר - הוסף לרשימה.

### חשבונות הכנסה במחשבשבת

החשבונות {927, 951, 7367} הם הכנסות. הכנסות נשמרות עם `amount` שלילי. בדשבורד מציגים אותן עם הסימן ההפוך (חיובי) ובצבע שונה.

### תקן הסולר - תקן עליון, לא ממוצע

`tools_registry.norm_high` הוא הגבול העליון של טווח תקין. חריגה = `actual_lph > norm_high * 1.15` (15% מעל הגבול).

### לוח זמן של בנייה - לא חודש קלנדרי תמיד

המערכת עובדת בחודשים קלנדריים (MM-YYYY) כי כך מגיעים הדוחות. אם בעתיד יבקשו תקופות חופפות (לדוגמה 15-15) - יידרש שינוי בסכמה.

## מודל AI

ברירת מחדל: `claude-haiku-4-5-20251001` - מהיר וזול. מתאים לשאילתות יומיומיות.

אם תרצה לשדרג ל-Sonnet/Opus עבור ניתוחים מורכבים יותר, החלף את `DEFAULT_MODEL` ב-`ai_tools.py`.
