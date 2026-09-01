@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
title GoGlobal Intelligence V5.4.1 Self Check

echo ==========================================
echo       GoGlobal Intelligence V5.4.1 Self Check
echo ==========================================

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Python environment missing. Run run_win.bat first.
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo [ERROR] Frontend dependencies missing. Run run_win.bat first.
  pause
  exit /b 1
)

echo [1/2] Backend tests...
pushd backend
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 (
  popd
  goto :failed
)
popd

echo [2/2] Frontend production build...
pushd frontend
call npm run build
if errorlevel 1 (
  popd
  goto :failed
)
popd

echo.
echo [OK] Backend tests and frontend build passed.
pause
exit /b 0

:failed
echo.
echo [ERROR] Self check failed. Keep this window open and send the error text.
pause
exit /b 1
