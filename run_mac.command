#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

MIN_NODE_MAJOR=22
MIN_NODE_MINOR=12
BUILD_ID="v538-20260829-final-polish-r2"
DEPS_MARKER="backend/.venv/.bordermargin_v538_deps"

printf '%s\n' "=========================================="
printf '%s\n' "       BorderMargin V5.3.8 Starter"
printf '%s\n' "       macOS / Intel & Apple Silicon"
printf '%s\n\n' "=========================================="

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] Node.js was not found. Install Node.js 22 LTS and run this file again."
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm was not found. Reinstall Node.js 22 LTS."
  exit 1
fi
NODE_VERSION=$(node -p "process.versions.node")
NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
NODE_MINOR=$(node -p "process.versions.node.split('.')[1]")
if [ "$NODE_MAJOR" -lt "$MIN_NODE_MAJOR" ] || { [ "$NODE_MAJOR" -eq "$MIN_NODE_MAJOR" ] && [ "$NODE_MINOR" -lt "$MIN_NODE_MINOR" ]; }; then
  echo "[ERROR] Node.js $NODE_VERSION is too old."
  echo "BorderMargin requires Node.js 22.12 or newer."
  exit 1
fi
echo "[OK] Node.js $NODE_VERSION"

find_python() {
  for cmd in python3 python3.13 python3.12 python3.11; do
    if command -v "$cmd" >/dev/null 2>&1 && "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
      echo "$cmd"; return 0
    fi
  done
  return 1
}
PY_CMD=$(find_python || true)
if [ -z "$PY_CMD" ]; then
  echo "[ERROR] Python 3.11 or newer was not found."
  echo "Install Python 3.12 from python.org, reopen Terminal, then run this file again."
  exit 1
fi
SYSTEM_PY_VERSION=$($PY_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "[OK] System Python $SYSTEM_PY_VERSION ($PY_CMD)"

[ -f .env ] || cp .env.example .env

# Python.org builds on macOS can miss the system CA bundle until certificates are installed.
# Reuse the macOS CA bundle for pip/requests when it exists; this keeps HTTPS verification enabled.
if [ -f /etc/ssl/cert.pem ]; then
  export SSL_CERT_FILE="${SSL_CERT_FILE:-/etc/ssl/cert.pem}"
  export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/etc/ssl/cert.pem}"
  export PIP_CERT="${PIP_CERT:-/etc/ssl/cert.pem}"
fi

REBUILD_VENV=0
if [ -x backend/.venv/bin/python ]; then
  if ! backend/.venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    OLD_PY=$(backend/.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || echo unknown)
    echo "[INFO] Existing virtual environment uses Python $OLD_PY and will be rebuilt."
    REBUILD_VENV=1
  fi
fi
if [ "$REBUILD_VENV" = "1" ]; then rm -rf backend/.venv; fi

if [ ! -x backend/.venv/bin/python ]; then
  echo "[1/6] Creating Python virtual environment..."
  "$PY_CMD" -m venv backend/.venv
else
  echo "[1/6] Python virtual environment already exists."
fi
PY_VERSION=$(backend/.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "[2/6] Python $PY_VERSION"

if [ ! -f "$DEPS_MARKER" ]; then
  echo "[3/6] Installing backend dependencies..."
  if ! backend/.venv/bin/python -m pip install --upgrade pip setuptools wheel; then
    echo "[ERROR] Python packages could not be downloaded over HTTPS."
    echo "Check the macOS certificate/network configuration and try again."
    exit 1
  fi
  backend/.venv/bin/python -m pip install --prefer-binary -r backend/requirements.txt
  touch "$DEPS_MARKER"
else
  echo "[3/6] Backend dependencies already installed."
fi

if [ ! -d frontend/node_modules ]; then
  echo "[4/6] Installing frontend dependencies..."
  (cd frontend && npm install)
else
  echo "[4/6] Frontend dependencies already installed."
fi

echo "[5/6] Validating frontend production build..."
(cd frontend && npm run build)

release_port() {
  local port="$1"; local pids
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  [ -z "$pids" ] && return 0
  if [ "$port" = "8000" ] && curl -fsS --max-time 1 http://127.0.0.1:8000/api/health 2>/dev/null | grep -q '"service":"BorderMargin API"'; then
    echo "[PORT] Closing previous BorderMargin API on port 8000..."; kill $pids 2>/dev/null || true; sleep 1; return 0
  fi
  if [ "$port" = "5173" ] && curl -fsS --max-time 1 http://127.0.0.1:5173 2>/dev/null | grep -q '<title>BorderMargin</title>'; then
    echo "[PORT] Closing previous BorderMargin UI on port 5173..."; kill $pids 2>/dev/null || true; sleep 1; return 0
  fi
  echo "[ERROR] Port $port is already used by another application."; exit 1
}

cleanup() {
  [ -n "${API_LOOP_PID:-}" ] && kill "$API_LOOP_PID" 2>/dev/null || true
  [ -n "${OPEN_PID:-}" ] && kill "$OPEN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[6/6] Preparing ports and starting services..."
release_port 8000
release_port 5173
(cd backend && while true; do .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000; echo "[WARN] API stopped; restarting in 2 seconds..."; sleep 2; done) &
API_LOOP_PID=$!

READY=0
for _ in $(seq 1 45); do
  if curl -fsS --max-time 1 http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "\"build\":\"$BUILD_ID\""; then READY=1; break; fi
  sleep 1
done
if [ "$READY" != "1" ]; then
  echo "[ERROR] The expected BorderMargin API build did not become ready."
  exit 1
fi

(
  for _ in $(seq 1 45); do
    if curl -fsS --max-time 1 http://127.0.0.1:5173 >/dev/null 2>&1; then
      open http://127.0.0.1:5173 >/dev/null 2>&1 || true
      exit 0
    fi
    sleep 1
  done
) &
OPEN_PID=$!

echo
echo "BorderMargin is starting. The browser will open automatically."
echo "UI:  http://127.0.0.1:5173"
echo "API: http://127.0.0.1:8000/docs"
echo "Press Ctrl+C once to stop both services."
echo
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
