@echo off
cd /d "%~dp0"
call setup_windows.bat
if errorlevel 1 goto failure
".venv-win312\Scripts\python.exe" main.py
if errorlevel 1 goto failure
exit /b 0
:failure
echo Setup or startup failed. See the message above.
pause
exit /b 1
