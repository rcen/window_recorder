echo on
call "%~dp0pVenv\Scripts\activate.bat"
cd "%~dp0" 
title WatchTime
C:\Windows\System32\timeout.exe 620
C:\Python310\python.exe analytics.py
:loop
C:\Python310\python.exe script.py
PowerShell -Command "Add-Type -AssemblyName PresentationFramework;[System.Windows.MessageBox]::Show('Need to Re-Start THIS!!','WARNING', 0, 48)"
goto loop
