@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo BrokenVault virtual environment was not found.
  echo Create it with: py -3.12 -m venv .venv
  pause
  exit /b 1
)
start "BrokenVault Server" cmd /k "call .venv\Scripts\activate.bat && python -m server"
timeout /t 2 /nobreak >nul
start "BrokenVault Web UI" cmd /k "call .venv\Scripts\activate.bat && python -m client.webapp"
start "BrokenVault UI" http://127.0.0.1:8010
endlocal
