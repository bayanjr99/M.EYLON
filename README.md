# Construction Audit System

מערכת ביקורת פנימית לפרויקטי בנייה - חברת מ. אילון אביב נכסים בע"מ.

## מה זה עושה

מאחד נתונים מ-3 מקורות לכל פרויקט × חודש:

1. **כרטיס הנהלה ממחשבשבת** (`chashbashevet.xlsx`) - כל החיובים החשבונאיים.
2. **דוח תדלוק** (`solar.xlsx`) - תדלוקים מ-Pointer / דלקן.
3. **דוח שעות כלים** (`hours.xlsx`) - שעות עבודה לפי כלי, מהמזכירה.

ומריץ עליהם 5 בדיקות אוטומטיות:

- צריכת סולר חריגה (ל'/ש' > תקן).
- תדלוקים ללא שעות עבודה.
- שעות יום חריגות (>14 או שליליות).
- חיובים גדולים מאוד (>100K ש"ח).
- תנועות עם מילות מפתח חשודות ("תיקון", "טעות", "לבטל").

הכל מוצג בדשבורד Streamlit עברי, עם שכבת AI (Claude Haiku) לשאילתות חופשיות.

## התקנה ראשונית

```bash
# 1. תלויות
pip install -r requirements.txt

# 2. ייצור קבצי reference (פעם אחת)
python scripts/seed_reference_data.py

# 3. הגדר API key ל-AI (אופציונלי)
echo ANTHROPIC_API_KEY=sk-ant-... > .env

# 4. הרץ את הדשבורד
streamlit run app.py
# או: start.bat (Windows) / ./start.sh (Linux/Mac)
```

הדשבורד יעלה על http://localhost:8501.

## הוספת פרויקט חדש

1. ערוך את `data/projects_registry.xlsx` - הוסף שורה עם:
   - `project_id` - מזהה קצר באנגלית (תואם שם תיקייה).
   - `project_name` - שם הפרויקט בעברית.
   - `site_name` - שם האתר ב-solar.xlsx (לסינון - השוואה רכה).
   - `status` - active / archived.
2. צור תיקייה `data/projects/<project_id>/`.
3. הוסף קובץ `data/projects/<project_id>/price_book.xlsx` (אופציונלי).

## הוספת חודש חדש

1. צור תיקייה `data/projects/<project_id>/MM-YYYY/`.
2. שים את הקבצים:
   - `chashbashevet.xlsx`
   - `solar.xlsx`
   - `hours.xlsx`
3. הרץ:
   ```bash
   python -c "from pipeline import build_master; build_master()"
   ```
4. רענן את הדשבורד.

## מבנה הפרויקט

ראה `CLAUDE.md` למבנה מלא ומידע ארכיטקטוני.

## בעיות נפוצות

- **הדשבורד עולה ריק** - לא רצת עוד `build_master()`. ראה "הוספת חודש חדש".
- **AI לא עובד** - חסר `ANTHROPIC_API_KEY` ב-`.env`.
- **פרויקט לא מופיע ב-sidebar** - בדוק ש-`projects_registry.xlsx` קיים ושמכיל את הפרויקט.
- **solar לא מסונן לפרויקט נכון** - בדוק שעמודת `site_name` ברגיסטרי מתאימה למה שיש ב-solar.xlsx (השוואה רכה אך לא קסם).
