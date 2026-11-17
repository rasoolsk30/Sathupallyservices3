#!/usr/bin/env bash
# Run the backend test suite.
#
# SAFETY: the suite drops and recreates the schema of a DEDICATED disposable
# PostgreSQL database. This script sets the explicit opt-in the harness requires.
# The harness itself still refuses unless the target is a *_test database on
# loopback that is not the configured application database.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi
export PYTHONPATH="$PWD"
export SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg://ssh_app:dev_local_only_change_me@127.0.0.1:5432/sathupally_test}"

echo "Test database: ${TEST_DATABASE_URL%%\?*}"
python3 -m pytest "$@"
exit $?
