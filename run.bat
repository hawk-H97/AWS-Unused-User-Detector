@echo off
REM Activates the venv (creating it via setup.bat if missing) and runs main.py
if not exist "venv" (
    echo [INFO] venv not found, running setup.bat first...
    call setup.bat
)

call venv\Scripts\activate.bat
python main.py
