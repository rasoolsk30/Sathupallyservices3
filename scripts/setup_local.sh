#!/usr/bin/env bash
# SATHUPALLY SERVICE HUB — local development setup (Linux/macOS/WSL).
# Windows without WSL: follow docs in README (manual steps are identical).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> 1/6 Python virtual environment"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt

echo "==> 2/6 PostgreSQL role + databases"
PG_SUPER="${PG_SUPERUSER:-postgres}"
DB_USER="${DB_USER:-ssh_app}"
DB_PASS="${DB_PASS:-dev_local_only_change_me}"
if command -v psql >/dev/null 2>&1; then
  sudo -u "$PG_SUPER" psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u "$PG_SUPER" psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
  sudo -u "$PG_SUPER" psql -tc "SELECT 1 FROM pg_database WHERE datname='sathupally'" | grep -q 1 || \
    sudo -u "$PG_SUPER" psql -c "CREATE DATABASE sathupally OWNER $DB_USER;"
  sudo -u "$PG_SUPER" psql -tc "SELECT 1 FROM pg_database WHERE datname='sathupally_test'" | grep -q 1 || \
    sudo -u "$PG_SUPER" psql -c "CREATE DATABASE sathupally_test OWNER $DB_USER;"
else
  echo "!! psql not found. Install PostgreSQL 16+ and create the databases manually (see README)."
  exit 1
fi

echo "==> 3/6 Environment file"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  python3 - "$SECRET" <<'PY'
import re, sys
p = "backend/.env"
s = open(p).read()
s = s.replace("JWT_SECRET=CHANGE_ME_RUN_SECRETS_SCRIPT", f"JWT_SECRET={sys.argv[1]}")
s = s.replace("CHANGE_ME", "dev_local_only_change_me")
open(p, "w").write(s)
PY
  echo "   created backend/.env with a generated JWT secret"
else
  echo "   backend/.env already exists — left untouched"
fi

echo "==> 4/6 Database migrations"
( cd backend && alembic upgrade head )

echo "==> 5/6 Reference data seed"
( cd backend && python -m app.seed )

echo "==> 6/6 Done"
cat <<'EOF'

Start the API:
    source .venv/bin/activate
    cd backend && uvicorn app.main:app --reload --port 8000 --no-proxy-headers

Create the first Super Admin (no demo accounts are shipped):
    cd backend
    ADMIN_INITIAL_PASSWORD='<choose-strong-password>' \
      python -m scripts.create_admin --phone 9876543210 --name "Owner Name"

Run behind a reverse proxy? Keep --no-proxy-headers and set TRUSTED_PROXIES to the
proxy IP/CIDR so the app (not uvicorn) decides whether X-Forwarded-For is trustworthy.

Run tests:
    cd backend && pytest
EOF
