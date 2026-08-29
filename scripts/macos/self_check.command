#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ ! -x backend/.venv/bin/python ]; then echo "[ERROR] Python environment missing. Run run_mac.command first."; exit 1; fi
if [ ! -d frontend/node_modules ]; then echo "[ERROR] Frontend dependencies missing. Run run_mac.command first."; exit 1; fi
echo "[1/2] Backend tests..."
(cd backend && .venv/bin/python -m pytest -q)
echo "[2/2] Frontend production build..."
(cd frontend && npm run build)
echo "[OK] Backend tests and frontend build passed."
