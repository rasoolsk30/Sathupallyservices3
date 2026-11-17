#!/usr/bin/env bash
# Restore a backup produced by backup_db.sh.
# SAFETY: requires an explicit --yes flag and refuses names containing 'prod'
# unless --i-know-this-is-production is also supplied.
set -euo pipefail
FILE="${1:?usage: restore_db.sh <backup.dump> <target_db_url> --yes [--i-know-this-is-production]}"
TARGET="${2:?target database URL required}"
shift 2
CONFIRM=false; PROD_OK=false
for arg in "$@"; do
  [ "$arg" = "--yes" ] && CONFIRM=true
  [ "$arg" = "--i-know-this-is-production" ] && PROD_OK=true
done
[ "$CONFIRM" = true ] || { echo "Refusing to restore without --yes"; exit 1; }
if echo "$TARGET" | grep -qi prod && [ "$PROD_OK" != true ]; then
  echo "Refusing: target looks like production. Re-run with --i-know-this-is-production after taking a fresh backup."
  exit 1
fi
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$TARGET" "$FILE"
echo "Restore complete. Run the verification queries in docs/BACKUP_RESTORE.md."
