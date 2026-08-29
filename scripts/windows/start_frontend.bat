@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%\frontend"
title BorderMargin UI
if not exist "node_modules" (
  echo [ERROR] Frontend dependencies are missing. Run run_win.bat first.
  pause
  exit /b 1
)
:ui_loop
call npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
set "UI_EXIT=%ERRORLEVEL%"
echo.
echo [WARN] BorderMargin UI stopped with exit code %UI_EXIT%.
echo [WARN] Restarting automatically in 2 seconds. Close this window to stop BorderMargin.
timeout /t 2 /nobreak >nul
goto :ui_loop
