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

REM Start habit tracking server in background (if not already running)
echo Checking habit server...
netstat -an | findstr "8042" >nul 2>&1
if errorlevel 1 (
    echo Starting habit tracking server...
    start /min pythonw.exe habit_server.py
    timeout /t 2 /nobreak >nul
    echo Habit server started on http://127.0.0.1:8042/habits
) else (
    echo Habit server already running
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
