@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === INFINITRIX SEARCH - setup ===

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Created .env from .env.example. Open .env and fill in your keys.
)

echo.
echo Setup finished. Edit .env, then run run.bat
pause
