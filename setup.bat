@echo off
REM ---------------------------------------------------------------------------
REM setup.bat
REM Automated environment setup for Windows.
REM Creates a Python virtual environment and installs all dependencies.
REM Run this ONCE (or whenever requirements.txt changes).
REM
REM Usage:
REM   setup.bat
REM ---------------------------------------------------------------------------
setlocal enabledelayedexpansion

echo ==================================================
echo  AWS Identity Center Inactive User Report - Setup
echo ==================================================

set PYTHON_BIN=

where python >nul 2>nul
if %errorlevel%==0 (
    set PYTHON_BIN=python
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set PYTHON_BIN=py
    )
)

if "%PYTHON_BIN%"=="" (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.9+ from https://www.python.org/downloads/
    echo         and make sure to check "Add Python to PATH" during install.
    exit /b 1
)

for /f "delims=" %%v in ('%PYTHON_BIN% --version') do echo [INFO] Using %%v

set VENV_DIR=venv

if not exist "%VENV_DIR%" (
    echo [INFO] Creating virtual environment in .\%VENV_DIR%
    %PYTHON_BIN% -m venv %VENV_DIR%
) else (
    echo [INFO] Virtual environment already exists, skipping creation.
)

call "%VENV_DIR%\Scripts\activate.bat"

echo [INFO] Upgrading pip
python -m pip install --upgrade pip >nul

echo [INFO] Installing dependencies from requirements.txt
pip install -r requirements.txt

if not exist "output" mkdir output

echo.
echo [SUCCESS] Setup complete.
echo.
echo Next steps:
echo   venv\Scripts\activate.bat
echo   python main.py
echo.
echo (Or just run run.bat which does both steps for you.)

endlocal
