@echo off
REM Spusti novou Qt desktop appku Calibre Meta Edit bez rucniho psani prikazu.
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0calibre_meta_qt.py"
) else (
    start "" python.exe "%~dp0calibre_meta_qt.py"
)
exit /b
