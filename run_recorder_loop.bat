@echo off
setlocal
cd /d "%~dp0"

REM Activate virtual environment
call "winrecord_env\Scripts\activate.bat"

title %COMPUTERNAME% "Window Recorder Loop"

:loop
python script.py
echo "Script stopped. Restarting in 5 seconds..."
timeout /t 5 >nul
goto loop
