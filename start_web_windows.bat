@echo off
cd /d "%~dp0"
call setup_windows.bat
if errorlevel 1 goto failure
start "" http://127.0.0.1:8000
".venv-win312\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto failure
exit /b 0
:failure
echo Setup or startup failed. See the message above.
pause
exit /b 1
