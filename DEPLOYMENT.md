# 🚀 זרימת פריסה — מקוד לפרודקשן

האתר **[m-eylon.streamlit.app](https://m-eylon.streamlit.app/)** מחובר ל-Streamlit Cloud,
שעוקב אחרי `origin/main` ב-GitHub (`bayanjr99/M.EYLON`).

> **כל שינוי שלא נדחף ל-`main` לא יופיע בפרודקשן** — לא משנה אם השתנה מקומית.
> Streamlit Cloud בונה את האתר מחדש אוטומטית תוך 1-2 דקות אחרי כל push ל-`main`.

## חוקים מחייבים

### 1. לא דוחפים ישירות ל-`main`

Auto-mode חוסם זאת. כל שינוי עובר דרך PR:

```bash
git checkout -b <feature-branch>
git add <specific files>
git commit -m "תיאור השינוי"
git push -u origin <feature-branch>
# פותחים PR ב-GitHub → ממזגים → main מתעדכן → Streamlit Cloud rebuilds
```

### 2. לפני push: לוודא שהקוד תקין

```bash
python -m compileall -q app.py pipeline.py core ui
python -c "import sys; sys.path.insert(0,'.'); import app"
```

### 3. קבצי נתונים שצריכים להגיע לענן

חייבים להיות tracked ב-git (לא ב-`.gitignore`):

| קובץ | סטטוס | מקור |
|---|---|---|
| `data/master.parquet` | ✓ tracked | `pipeline.build_master()` |
| `data/site_tracking.parquet` | ✓ tracked | `pipeline.build_site_tracking_parquet()` |
| `data/fuel_invoices.parquet` | ✓ tracked | `pipeline.build_fuel_invoices_parquet()` |
| `data/fuel_tracker.parquet` | ✓ tracked | `pipeline.build_fuel_tracker_parquet()` |
| `data/project_control.sqlite` | ✓ tracked | SQLite, נשמר ידנית |
| `data/projects/*/` | ✗ gitignored | xlsx גולמיים — מקומית בלבד |

אם משנים פייפליין שמייצר parquet — חייב להריץ
`python -c "from pipeline import build_master; build_master()"` **לפני ה-commit**,
ולכלול את ה-parquet החדש בקומיט.

### 4. אחרי merge — לבדוק שהפרודקשן עומד

```bash
# health check — 200/303 = חי
curl -sI https://m-eylon.streamlit.app/ -o /dev/null -w "HTTP %{http_code}\n"
```

ולפתוח בדפדפן:
- [ ] האתר נטען (אין rainbow screen של "Error running app")
- [ ] השינוי הספציפי באמת מופיע
- [ ] המסכים המרכזיים עובדים (פרויקטים → לחיצה על פרויקט → טאבים)
- [ ] אין שגיאות אדומות ב-console / Streamlit error banner

---

## Checklist פריסה (העתק-הדבק)

- [ ] שינוי מקומי בקבצים הנכונים
- [ ] `python -m compileall -q app.py pipeline.py core ui` עובר ללא שגיאות
- [ ] `python -c "import sys; sys.path.insert(0,'.'); import app"` עובר
- [ ] אם שונו פייפליינים → `build_master()` הורץ והפרקטים החדשים בקומיט
- [ ] `git status` נקי מ-junk
- [ ] `git diff` נראה הגיוני (אין שינויי הזחה / קבצים זמניים)
- [ ] `git checkout -b <feature-branch>`
- [ ] `git add <specific files>` (לא `-A` עיוור)
- [ ] `git commit -m "תיאור ברור"`
- [ ] `git push -u origin <feature-branch>`
- [ ] לפתוח את ה-URL של PR שמתקבל בפלט push
- [ ] למלא Title + Description
- [ ] לוודא "✓ Able to merge"
- [ ] "Merge pull request" → "Confirm merge"
- [ ] להמתין 1-2 דקות → לרענן את `m-eylon.streamlit.app`
- [ ] לעבור על הסעיפים בסעיף 4 לעיל
- [ ] למחוק את ה-branch ב-GitHub UI ("Delete branch") אחרי merge מוצלח

---

## טיפול בכשלים בפרודקשן

### האתר מציג "Error running app"
- בדוק את ה-Streamlit Cloud logs (Dashboard → Manage app → Logs).
- ה-rollback המהיר ביותר: ב-GitHub → Pull requests → reverted PR → Merge.
- או `git revert <bad-commit-sha>` + push ל-main דרך PR חירום.

### האתר לא התעדכן אחרי merge
- ודא שה-commit באמת על `origin/main`: `git log origin/main --oneline -3`.
- אם כן — חכה עוד דקה. Streamlit Cloud לפעמים איטי.
- אם חולפות יותר מ-5 דקות — היכנס ל-Streamlit Cloud Dashboard → "Reboot app".

### ה-PR מציג קונפליקטים
- מי שמיזג PR קודם — הקדים אותך.
- `git checkout <my-branch> && git fetch origin && git rebase origin/main`
- פתור קונפליקטים מקומית → `git push --force-with-lease origin <my-branch>`
- (Force-push לbranch של PR הוא בסדר; לא ל-main!)
