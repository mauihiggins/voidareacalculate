@echo off
setlocal
cd /d "%~dp0"
if exist server.py if exist requirements.txt goto project_ready
if exist "%USERPROFILE%\Desktop\VoidInspect-web-windows-fix\server.py" cd /d "%USERPROFILE%\Desktop\VoidInspect-web-windows-fix"
if exist server.py if exist requirements.txt goto project_ready
echo Place this file in the extracted VoidInspect folder, then double-click it.
goto failed
:project_ready
echo [1/3] Checking Python and restoring the installation...
set "VOID_PY=.venv-win312\Scripts\python.exe"
if exist "%VOID_PY%" goto validate
py -3.12 -c "import sys,struct,platform; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 1)" >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -m venv .venv-win312
if errorlevel 1 goto failed
goto validate
:try_python
python -c "import sys,struct,platform; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 1)" >nul 2>&1
if errorlevel 1 goto missing
python -m venv .venv-win312
if errorlevel 1 goto failed
:validate
"%VOID_PY%" -c "import sys,struct,platform; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 1)"
if errorlevel 1 goto missing
"%VOID_PY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto pip_ready
echo Restoring pip with Python ensurepip...
"%VOID_PY%" -m ensurepip --upgrade --default-pip
if errorlevel 1 goto pip_failed
:pip_ready
"%VOID_PY%" -m pip install --upgrade pip
if errorlevel 1 goto failed
"%VOID_PY%" -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto failed
echo [2/3] Checking application dependencies...
"%VOID_PY%" -c "import numpy, PIL, scipy, fastapi, uvicorn; import server"
if errorlevel 1 goto failed
echo [3/3] Starting VOID INSPECT. Keep this window open.
start "" /b powershell.exe -NoProfile -Command "for ($i=0; $i -lt 60; $i++) { try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8000'; break } } catch {}; Start-Sleep -Seconds 1 }"
"%VOID_PY%" -m uvicorn server:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto failed
exit /b 0
:missing
echo Python 3.12 x64 is required. Install the Windows installer (64-bit):
echo https://www.python.org/downloads/release/python-31210/
echo Include Python Launcher during installation, then run this file again.
echo Existing .venv and images are preserved.
goto failed

:pip_failed
echo Could not restore pip. Run the Python 3.12 installer and select Repair, then retry.
goto failed

:failed
echo Setup could not finish. Keep this message for troubleshooting.
pause
exit /b 1
