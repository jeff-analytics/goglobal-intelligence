@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%\backend"
title GoGlobal Intelligence API
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run run_win.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "from app.config import refresh_settings; s=refresh_settings(); print('[CONFIG] eBay:', 'configured' if (s.ebay_client_id and s.ebay_client_secret) else 'not configured', '| env:', s.ebay_env, '| source:', '+'.join(s.config_sources) or 'none')"
:api_loop
echo [API] Starting GoGlobal Intelligence API on http://localhost:8000 ...
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
set "API_EXIT=%ERRORLEVEL%"
echo.
echo [WARN] GoGlobal Intelligence API stopped with exit code %API_EXIT%.
echo [WARN] Restarting automatically in 2 seconds. Close this window to stop GoGlobal Intelligence.
timeout /t 2 /nobreak >nul
goto :api_loop
