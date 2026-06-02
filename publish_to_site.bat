@echo off
REM ── פרסום נתוני DATA מקומיים לאתר בלחיצה אחת ─────────────────
REM 1) בונה master.parquet מחדש + מסנכרן פרויקטים ל-Neon
REM 2) git add / commit / push  → האתר מתעדכן לבד תוך ~1-2 דקות
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   פרסום נתונים לאתר
echo ============================================================

python scripts\publish_to_site.py
if errorlevel 1 (
    echo.
    echo [!] ההכנה נכשלה - לא דוחפים ל-git. ראה הודעות למעלה.
    pause
    exit /b 1
)

echo.
echo --- דוחף ל-GitHub ---
git add data\master.parquet data\projects_registry.xlsx data\manual
git commit -m "publish: update site data"
if errorlevel 1 (
    echo [i] אין שינויים חדשים ל-commit, או ה-commit נכשל.
)
git push
if errorlevel 1 (
    echo [!] git push נכשל. בדוק חיבור/הרשאות ונסה שוב.
    pause
    exit /b 1
)

echo.
echo [ok] נדחף. האתר יתעדכן לבד תוך כ-1-2 דקות.
pause
