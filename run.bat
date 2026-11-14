@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

if not exist .env (
    echo .env not found. Run setup.bat, then fill in your keys in .env
    pause
    exit /b 1
)

set PYTHONUTF8=1
".venv\Scripts\python.exe" bot.py
echo.
echo The bot has stopped.
pause
