echo on
call "%~dp0pVenv\Scripts\activate.bat"
cd "%~dp0" 
python analytics.py
:loop
python script.py
goto loop
