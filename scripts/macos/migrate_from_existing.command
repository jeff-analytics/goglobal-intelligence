#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
echo "==============================================="
echo " BorderMargin V5.3.x -> GoGlobal Intelligence V5.4.1 Data Migration macOS"
echo "==============================================="
read -r -p "Drag your existing BorderMargin V5.3.x folder here, then press Enter: " OLD_DIR
OLD_DIR=${OLD_DIR%\'}; OLD_DIR=${OLD_DIR#\'}; OLD_DIR=${OLD_DIR%\"}; OLD_DIR=${OLD_DIR#\"}
OLD_DIR=${OLD_DIR//\\ / }
if [ ! -d "$OLD_DIR" ]; then echo "[ERROR] Folder not found: $OLD_DIR"; exit 1; fi
[ -f "$OLD_DIR/.env" ] && cp "$OLD_DIR/.env" .env
if [ ! -f .env ] && [ -f "$OLD_DIR/backend/.env" ]; then cp "$OLD_DIR/backend/.env" .env; fi
mkdir -p backend/data
for db in "$OLD_DIR/backend/data/bordermargin.db" "$OLD_DIR/backend/bordermargin.db" "$OLD_DIR/bordermargin.db"; do [ -f "$db" ] && cp "$db" backend/data/bordermargin.db && break; done
[ -d "$OLD_DIR/backend/data/ebay_taxonomy" ] && rm -rf backend/data/ebay_taxonomy && cp -R "$OLD_DIR/backend/data/ebay_taxonomy" backend/data/ebay_taxonomy
[ -f "$OLD_DIR/backend/data/hs_reference.json" ] && cp "$OLD_DIR/backend/data/hs_reference.json" backend/data/hs_reference.json
echo "[DONE] Local settings, database and reusable caches were copied."
echo "[DONE] Run ./run_mac.command from the repository root."
