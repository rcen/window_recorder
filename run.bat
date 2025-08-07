@echo off
setlocal

REM Check for virtual environment
if not exist "winrecord_env" (
    echo "Creating virtual environment..."
    python -m venv winrecord_env
)

REM Activate virtual environment
call "winrecord_env\Scripts\activate.bat"

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
