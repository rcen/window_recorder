@echo off
REM Run regression tests before committing
REM Usage: run_tests.bat

echo ============================================
echo  Window Recorder - Regression Tests
echo ============================================
echo.

cd /d %~dp0

REM Activate virtual environment if it exists
if exist winrecord_env\Scripts\activate.bat (
    call winrecord_env\Scripts\activate.bat
)

echo Running regression tests...
echo.

python -m pytest tests/test_regression.py -v --tb=short

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================
    echo  TESTS FAILED - DO NOT COMMIT!
    echo ============================================
    exit /b 1
) else (
    echo.
    echo ============================================
    echo  ALL TESTS PASSED - OK to commit
    echo ============================================
    exit /b 0
)
