@echo off
setlocal
cd /d "%~dp0"
set "VOID_PY=.venv-win312\Scripts\python.exe"
if exist "%VOID_PY%" goto validate
py -3.12 -c "import sys,struct,platform; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 1)" >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -m venv .venv-win312
if errorlevel 1 exit /b 1
goto validate
:try_python
python -c "import sys,struct,platform; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64') else 1)" >nul 2>&1
if errorlevel 1 goto missing
python -m venv .venv-win312
if errorlevel 1 exit /b 1
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
if errorlevel 1 exit /b 1
"%VOID_PY%" -m pip install --only-binary=:all: -r requirements.txt
exit /b %errorlevel%
:missing
echo Python 3.12 x64 is required. Install the Windows installer (64-bit):
echo https://www.python.org/downloads/release/python-31210/
echo Include Python Launcher during installation, then run this file again.
echo Existing .venv and images are preserved.
exit /b 1

:pip_failed
echo Could not restore pip. Run the Python 3.12 installer and select Repair, then retry.
exit /b 1
