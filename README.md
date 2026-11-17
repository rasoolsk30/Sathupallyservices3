# SATHUPALLY SERVICE HUB

**Your Local Services. One Trusted Platform.**
Hyperlocal services marketplace for Sathupally Mandal, Telangana — Telugu + English.

> Status: **under construction — backend only (Milestone 2.5 / R2.3)**. The FastAPI backend,
> PostgreSQL schema and automated tests exist. No frontend, no admin dashboard and no deployment
> automation exist yet. See `CHANGELOG.md` and `TEST-REPORT.md` for exactly what works today;
> nothing in this repository claims production readiness.

## Repository layout

```
backend/    FastAPI + SQLAlchemy + Alembic (PostgreSQL) — the only application code delivered
docs/       ARCHITECTURE.md, CAPABILITY-REPORT.md, KNOWN-LIMITATIONS.md
scripts/    local setup, test runner, backup/restore, release packaging
delivery/   milestone ZIPs (also uploaded to the owner's Google Drive)
```

**Not yet present:** `frontend/` (React + TypeScript + Vite PWA for customer / provider /
employee / admin) has **not** been started — it is Milestone 3 and is blocked pending owner
approval of Milestone 2. Until it is delivered this repository contains a backend API only: there
is no browser UI, no installable PWA and no end-to-end test evidence.

## Quick start (Linux/macOS)

```bash
bash scripts/setup_local.sh        # installs deps, creates DBs, migrates, seeds reference data
cd backend && source ../.venv/bin/activate 2>/dev/null || true
uvicorn app.main:app --reload --port 8000 --no-proxy-headers
```

## Quick start (Windows, no Docker)

```powershell
# 1. Install Python 3.12+ and PostgreSQL 16+ and add both to PATH
# 2. In the project root:
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
# 3. Create databases (in psql as the postgres superuser):
#    CREATE USER ssh_app WITH PASSWORD '<choose-a-password>';
#    CREATE DATABASE sathupally OWNER ssh_app;
#    CREATE DATABASE sathupally_test OWNER ssh_app;
copy backend\.env.example backend\.env   # then edit DATABASE_URL and JWT_SECRET
cd backend
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000 --no-proxy-headers
```

A full installation guide (`docs/INSTALL_LOCAL.md`) is **not yet written** — it is scheduled for
Milestone 11 packaging. The two quick-start blocks above are the only setup instructions that
exist today, and they are what has actually been exercised in this environment.

## Running the test suite (safe by design)

The suite DROPs and recreates the schema of a **dedicated disposable** database. It refuses to
run unless you explicitly opt in, and it verifies the target is a `*_test` database on loopback
that is not your application database:

```bash
bash scripts/run_tests.sh          # sets SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1 and runs pytest
```

The run also requires an **application** `DATABASE_URL` (environment variable or `backend/.env`)
so the guard can prove the test database is a different database. If it is missing, unparseable or
names no database, the suite refuses to start and exits with code 2 rather than running the
destructive reset without collision protection.

See `docs/KNOWN-LIMITATIONS.md` for the current limitation list, including the single-worker
rate-limiting constraint.

## Documentation index

- `docs/ARCHITECTURE.md` — system design and rules
- `docs/CAPABILITY-REPORT.md` — what this build session could and could not do
- `docs/KNOWN-LIMITATIONS.md` — every known limitation, with impact and workaround
- `CHANGELOG.md` — milestone-by-milestone file-level changes
- `TEST-REPORT.md` — commands actually executed and their real results
