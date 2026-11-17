#!/usr/bin/env bash
# Build a delivery ZIP of the project, excluding secrets, caches and local data.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:?usage: make_zip.sh <archive-name> }"
OUT_DIR="$ROOT/delivery"
mkdir -p "$OUT_DIR"
cd "$ROOT"
zip -rq "$OUT_DIR/$NAME" . \
  -x "*/node_modules/*" "*/node_modules" \
  -x "*/.venv/*" "*/.venv" \
  -x "*/__pycache__/*" "*/__pycache__" \
  -x "*/.pytest_cache/*" "*/.pytest_cache" \
  -x "*/dist/*" "*/dist" \
  -x "storage/*" "storage" \
  -x "backups/*" "backups" \
  -x "delivery/*" "delivery" \
  -x ".git/*" ".git" "*/.git/*" "*/.git" \
  -x "*/.env" \
  -x "*.pyc" "*/.DS_Store"
echo "Created: $OUT_DIR/$NAME"
unzip -l "$OUT_DIR/$NAME" | tail -1
