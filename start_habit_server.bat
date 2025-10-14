@echo off
REM Start the habit tracking server
echo Starting habit tracking server...
start /min C:\projects\window_recorder\winrecord_env\Scripts\pythonw.exe habit_server.py
timeout /t 2 /nobreak >nul
echo Habit server started on http://127.0.0.1:8042/habits
echo.
echo You can now open html\index.html and your habit checkboxes will work!
pause
