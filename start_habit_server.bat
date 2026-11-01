@echo off
REM Start the habit tracking & dashboard HTTP server
cd /d "%~dp0"
echo Starting habit tracking server...
start /min "" "%~dp0winrecord_env\Scripts\pythonw.exe" habit_server.py
timeout /t 2 /nobreak >nul
echo Habit server started on http://127.0.0.1:8042/
echo.
echo Open http://127.0.0.1:8042/ in your browser to view the interactive dashboard!
pause
