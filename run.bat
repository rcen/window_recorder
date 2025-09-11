@echo off
setlocal
cd /d "%~dp0"

REM Check for virtual environment
if not exist "venv" (
    echo "Creating virtual environment..."
    python -m venv venv
)

REM Activate virtual environment
call "venv\Scripts\activate.bat"

REM Install dependencies if --new is passed
if "%1"=="--new" (
    pip install -r requirements.txt
)

REM Run analytics
python analytics.py

REM Run the main script in a loop
:loop
python script.py
echo "Script stopped. Restarting in 5 seconds..."
timeout /t 5
goto loop
