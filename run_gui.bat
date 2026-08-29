@echo off
REM Double-click launcher for the MoneyPrinter GUI on Windows.
REM Keeps the window open if something goes wrong so you can read the error.

cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 gui.py
) else (
    python gui.py
)

if errorlevel 1 (
    echo.
    echo The GUI exited with an error.
    echo.
    echo Most common causes:
    echo   * Python is not installed or not on PATH  -  https://python.org/downloads
    echo     ^(tick "Add python.exe to PATH" in the installer^)
    echo   * Missing packages  -  run:  pip install yfinance openpyxl tzdata
    echo.
    pause
)
