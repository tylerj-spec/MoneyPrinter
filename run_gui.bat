@echo off
REM Launch the integrated desktop app, preferring this checkout's virtualenv.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 app.py
) else (
    py -3 -X utf8 app.py
)
if errorlevel 1 (
    echo.
    echo The app exited with an error. See docs\LOCAL_QUICKSTART.md.
    pause
)
