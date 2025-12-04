@echo off
setlocal
cd /d "%~dp0"

title %COMPUTERNAME% "Track your time" 
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

REM Start habit tracking and must-done server in background (if not already running)
echo Checking habit/must-done server...
netstat -an | findstr "8042" >nul 2>&1
if errorlevel 1 (
    echo Starting habit tracking and must-done server...
    start "" /min "%~dp0winrecord_env\Scripts\pythonw.exe" habit_server.py
    timeout /t 2 /nobreak >nul
    echo Server started on http://127.0.0.1:8042
    echo   - Habits endpoint: /habits
    echo   - Must-done endpoint: /must_done/update
) else (
    echo Habit/must-done server already running on port 8042
)

REM Run analytics
python recategorize.py
python analytics.py

REM Run the main script in a loop
:loop
python script.py
echo "Script stopped. Restarting in 5 seconds..."
timeout /t 5
goto loop
