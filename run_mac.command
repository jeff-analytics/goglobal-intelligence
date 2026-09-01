#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

MIN_NODE_MAJOR=22
MIN_NODE_MINOR=12
EXPECTED_BUILD_ID="v541-20260901-algorithms-ai-config-r2"
VENV_PY="backend/.venv/bin/python"
BACKEND_LOG="backend/data/runtime/goglobal_backend.log"

printf '%s\n' "=========================================="
printf '%s\n' "       GoGlobal Intelligence V5.4.1 Starter"
printf '%s\n' "       macOS / Intel & Apple Silicon"
printf '%s\n\n' "=========================================="

# Localhost must never be routed through a corporate/VPN HTTP proxy.
export NO_PROXY="127.0.0.1,localhost,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"

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
  echo "GoGlobal Intelligence requires Node.js 22.12 or newer."
  exit 1
fi
echo "[OK] Node.js $NODE_VERSION"

find_python() {
  for cmd in python3.12 python3.13 python3.11 python3; do
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
if [ -f /etc/ssl/cert.pem ]; then
  export SSL_CERT_FILE="${SSL_CERT_FILE:-/etc/ssl/cert.pem}"
  export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/etc/ssl/cert.pem}"
  export PIP_CERT="${PIP_CERT:-/etc/ssl/cert.pem}"
fi

# Rebuild stale/broken venvs, including a venv whose base Python was removed.
REBUILD_VENV=0
if [ -e backend/.venv ] && [ ! -x "$VENV_PY" ]; then
  echo "[INFO] Existing virtual environment is broken and will be rebuilt."
  REBUILD_VENV=1
elif [ -x "$VENV_PY" ]; then
  if ! "$VENV_PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    OLD_PY=$("$VENV_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || echo unknown)
    echo "[INFO] Existing virtual environment uses Python $OLD_PY and will be rebuilt."
    REBUILD_VENV=1
  elif ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    echo "[INFO] Existing virtual environment has no working pip and will be rebuilt."
    REBUILD_VENV=1
  fi
fi
if [ "$REBUILD_VENV" = "1" ]; then rm -rf backend/.venv; fi

if [ ! -x "$VENV_PY" ]; then
  echo "[1/6] Creating Python virtual environment..."
  "$PY_CMD" -m venv backend/.venv
else
  echo "[1/6] Python virtual environment already exists."
fi
PY_VERSION=$("$VENV_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "[2/6] Python $PY_VERSION"

# Dependency marker follows requirements.txt content instead of a fixed release marker.
REQ_HASH=$(shasum -a 256 backend/requirements.txt | awk '{print $1}')
DEPS_MARKER="backend/.venv/.goglobal_deps_${REQ_HASH}"
if [ ! -f "$DEPS_MARKER" ]; then
  echo "[3/6] Installing backend dependencies..."
  if ! "$VENV_PY" -m pip install --upgrade pip setuptools wheel; then
    echo "[ERROR] Python packages could not be downloaded over HTTPS."
    echo "Check the macOS certificate/network configuration and try again."
    exit 1
  fi
  "$VENV_PY" -m pip install --prefer-binary -r backend/requirements.txt
  rm -f backend/.venv/.goglobal_deps_* 2>/dev/null || true
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

local_curl() {
  curl --noproxy '*' "$@"
}

release_port() {
  local port="$1" pids
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  [ -z "$pids" ] && return 0
  if [ "$port" = "8000" ] && local_curl -fsS --max-time 1 http://127.0.0.1:8000/api/health 2>/dev/null | grep -Eq '"service":"(GoGlobal Intelligence|BorderMargin) API"'; then
    echo "[PORT] Closing previous GoGlobal/BorderMargin API on port 8000..."
    kill $pids 2>/dev/null || true
    sleep 1
    return 0
  fi
  if [ "$port" = "5173" ] && local_curl -fsS --max-time 1 http://127.0.0.1:5173 2>/dev/null | grep -Eq '<title>(GoGlobal Intelligence|BorderMargin)</title>'; then
    echo "[PORT] Closing previous GoGlobal/BorderMargin UI on port 5173..."
    kill $pids 2>/dev/null || true
    sleep 1
    return 0
  fi
  echo "[ERROR] Port $port is already used by another application."
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  exit 1
}

API_PID=""
cleanup() {
  if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[6/6] Preparing ports and starting services..."
release_port 8000
release_port 5173
mkdir -p "$(dirname "$BACKEND_LOG")"
: > "$BACKEND_LOG"

# Use an absolute interpreter path and keep the backend log visible on failure.
VENV_PY_ABS="$(pwd)/$VENV_PY"
(
  cd backend
  exec "$VENV_PY_ABS" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) >"$BACKEND_LOG" 2>&1 &
API_PID=$!

echo "[INFO] Backend PID: $API_PID"
echo "[INFO] Backend log: $BACKEND_LOG"

READY=0
LAST_HEALTH=""
for i in $(seq 1 90); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo
    echo "[ERROR] GoGlobal Intelligence API exited during startup."
    echo "---------- backend log ----------"
    tail -n 120 "$BACKEND_LOG" 2>/dev/null || true
    echo "---------------------------------"
    exit 1
  fi

  LAST_HEALTH=$(local_curl -fsS --max-time 1 http://127.0.0.1:8000/api/health 2>/dev/null || true)
  if [ -n "$LAST_HEALTH" ] && printf '%s' "$LAST_HEALTH" | "$VENV_PY" -c '
import json, sys
expected = sys.argv[1]
try:
    body = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
ok = body.get("service") == "GoGlobal Intelligence API" and body.get("build") == expected
raise SystemExit(0 if ok else 1)
' "$EXPECTED_BUILD_ID"; then
    READY=1
    break
  fi

  if [ $((i % 10)) -eq 0 ]; then
    echo "[WAIT] API startup ${i}s..."
  fi
  sleep 1
done

if [ "$READY" != "1" ]; then
  echo
  echo "[ERROR] The expected GoGlobal Intelligence API build did not become ready."
  if [ -n "$LAST_HEALTH" ]; then
    echo "Health response: $LAST_HEALTH"
  else
    echo "Health endpoint did not return a response."
  fi
  echo "---------- backend log ----------"
  tail -n 120 "$BACKEND_LOG" 2>/dev/null || true
  echo "---------------------------------"
  exit 1
fi

echo "[OK] GoGlobal Intelligence API is ready."

(
  for _ in $(seq 1 60); do
    if local_curl -fsS --max-time 1 http://127.0.0.1:5173 >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then
        open http://127.0.0.1:5173 >/dev/null 2>&1 || true
      fi
      exit 0
    fi
    sleep 1
  done
) &

echo
echo "GoGlobal Intelligence is starting. The browser will open automatically."
echo "UI:  http://127.0.0.1:5173"
echo "API: http://127.0.0.1:8000/docs"
echo "Press Ctrl+C once to stop both services."
echo
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
