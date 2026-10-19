@echo off
setlocal
cd /d "%~dp0"
docker info >nul 2>&1
if errorlevel 1 (
  echo Start Docker Desktop, wait until it is ready, then run this file again.
  pause
  exit /b 1
)
if not exist .runtime mkdir .runtime
docker compose up -d --build --wait
if errorlevel 1 (
  echo Docker startup failed. See the error above.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8001
exit /b 0
