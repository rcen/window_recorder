@echo off
REM Backup local database to remote Neon PostgreSQL

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "winrecord_env\Scripts\activate.bat" (
    call "winrecord_env\Scripts\activate.bat"
)

echo.
echo ============================================
echo  Database Backup to Remote
echo ============================================
echo.
echo This will backup your local SQLite database
echo to the remote PostgreSQL (Neon) database.
echo.
echo Press Ctrl+C to cancel, or
pause

python backup_to_remote.py

echo.
echo ============================================
pause
