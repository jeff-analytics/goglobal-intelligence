@echo off
setlocal
cd /d "%~dp0"
title GoGlobal Intelligence Setup

echo ==========================================
echo          GoGlobal Intelligence V5.4.1 Starter
echo ==========================================
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js was not found.
  echo Install Node.js LTS, then run this file again.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm was not found.
  echo Reinstall Node.js 22 LTS, then run this file again.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%V in (`node -p "process.versions.node"`) do set "NODE_VERSION=%%V"
powershell -NoProfile -Command "if([version]'%NODE_VERSION%' -ge [version]'22.12.0'){exit 0}else{exit 1}"
if errorlevel 1 (
  echo [ERROR] Node.js %NODE_VERSION% is too old.
  echo GoGlobal Intelligence requires Node.js 22.12 or newer.
  echo Install Node.js 22 LTS, reopen Command Prompt, then run this file again.
  pause
  exit /b 1
)
echo [OK] Node.js %NODE_VERSION%

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
)

set "PY_LAUNCHER="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PY_LAUNCHER=py -3.12"
  if not defined PY_LAUNCHER py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PY_LAUNCHER=py -3.11"
  if not defined PY_LAUNCHER py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PY_LAUNCHER=py -3"
)
if not defined PY_LAUNCHER (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PY_LAUNCHER=python"
  )
)
if not defined PY_LAUNCHER (
  echo [ERROR] Python 3.11 or newer was not found.
  echo Install Python 3.12, reopen Command Prompt, then run this file again.
  pause
  exit /b 1
)

if exist "backend\.venv\Scripts\python.exe" (
  "backend\.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo [INFO] Existing Python virtual environment is too old and will be rebuilt.
    rmdir /S /Q "backend\.venv"
  )
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/6] Creating Python virtual environment...
  %PY_LAUNCHER% -m venv "backend\.venv"
  if errorlevel 1 goto :failed
) else (
  echo [1/6] Python virtual environment already exists.
)

echo [2/6] Python version:
"backend\.venv\Scripts\python.exe" --version
"backend\.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo [ERROR] GoGlobal Intelligence requires Python 3.11 or newer.
  pause
  exit /b 1
)

if exist "backend\.venv\.goglobal_v541_r2_deps" (
  echo [3/6] Backend dependencies already installed.
) else (
  echo [3/6] Installing backend dependencies...
  "backend\.venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
  if errorlevel 1 goto :failed
  "backend\.venv\Scripts\python.exe" -m pip install --prefer-binary -r "backend\requirements.txt"
  if errorlevel 1 goto :failed
  type nul > "backend\.venv\.goglobal_v541_r2_deps"
)

if exist "frontend\node_modules" (
  echo [4/6] Frontend dependencies already installed.
) else (
  echo [4/6] Installing frontend dependencies...
  pushd "frontend"
  call npm install
  if errorlevel 1 (
    popd
    goto :failed
  )
  popd
)

if exist "frontend\.goglobal_v541_r2_build_ok" (
  echo [5/6] Frontend build already validated.
) else (
  echo [5/6] Validating frontend production build...
  pushd "frontend"
  call npm run build
  if errorlevel 1 (
    popd
    echo.
    echo [ERROR] Frontend build validation failed. GoGlobal Intelligence will not start with a broken UI.
    goto :failed
  )
  type nul > ".goglobal_v541_r2_build_ok"
  popd
)

echo [6/6] Preparing local ports...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\prepare_ports.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] GoGlobal Intelligence could not safely claim ports 8000 and 5173.
  echo Close the application reported above, then run this file again.
  pause
  exit /b 1
)

echo [6/6] Starting GoGlobal Intelligence API...
start "GoGlobal Intelligence API" cmd /k call "%~dp0scripts\windows\start_backend.bat"
echo Waiting for the exact V5.4.1 backend build...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 45;$i++){ try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1; if($h.service -eq 'GoGlobal Intelligence API' -and $h.build -eq 'v541-20260901-algorithms-ai-config-r4'){$ok=$true;break} } catch {}; Start-Sleep -Seconds 1 }; if($ok){exit 0}else{exit 1}"
if errorlevel 1 (
  echo [ERROR] The expected GoGlobal Intelligence API build did not become ready.
  echo Check the GoGlobal Intelligence API window.
  pause
  exit /b 1
)

echo Starting GoGlobal Intelligence UI...
start "GoGlobal Intelligence UI" cmd /k call "%~dp0scripts\windows\start_frontend.bat"

echo.
echo GoGlobal Intelligence is starting in two windows.
echo UI:  http://127.0.0.1:5173
echo API: http://localhost:8000/docs
echo.
echo Waiting for the UI server to become ready...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 45;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173' -TimeoutSec 1; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){$ok=$true;break} } catch {}; Start-Sleep -Seconds 1 }; if($ok){exit 0}else{exit 1}"
if errorlevel 1 (
  echo [WARN] UI did not answer within 45 seconds. Check the GoGlobal Intelligence UI window.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:5173"
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Keep this window open and send the error text or a screenshot.
pause
exit /b 1
