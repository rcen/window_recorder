echo on
:loop
call "%~dp0pVenv\Scripts\activate.bat"
cd "%~dp0" && python script.py
goto loop
