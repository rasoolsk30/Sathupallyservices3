#!/usr/bin/env bash
# Timestamped PostgreSQL backup (custom format, restorable with pg_restore).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a
: "${DATABASE_URL:?DATABASE_URL not set}"
DB_URL="${DATABASE_URL/postgresql+psycopg:\/\//postgresql://}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${BACKUP_DIR:-$ROOT/backups}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/sathupally_${STAMP}.dump"
pg_dump --format=custom --no-owner --no-privileges --dbname="$DB_URL" --file="$OUT"
echo "Backup written: $OUT ($(du -h "$OUT" | cut -f1))"
echo "Verify: pg_restore --list '$OUT' | head"
