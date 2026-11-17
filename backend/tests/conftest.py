"""Test harness.

The schema is built by running the REAL Alembic migrations against a **dedicated,
disposable** PostgreSQL database. Destructive reset is gated by `tests/guards.py`,
which requires an explicit opt-in (`SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1`), a
`*_test` database-name suffix, a loopback host, and a URL that does not collide with
the configured application database.

Two further details:

1. The `client` fixture installs a database dependency with **production semantics**
   (commit on success, rollback on exception). An earlier revision used a lenient
   override that never rolled back, which silently masked two real defects.
2. `live_server` starts a real uvicorn instance so concurrency tests exercise genuine
   parallel requests with independent database connections and row-level locking.
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import threading
import time

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://ssh_app:dev_local_only_change_me@127.0.0.1:5432/sathupally_test",
)

# Capture the application's own database URL BEFORE overriding DATABASE_URL below.
CONFIGURED_APP_DB_URL = os.environ.get("DATABASE_URL")

# Must be set BEFORE importing app modules (settings are cached on import).
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789-0123456789-0123456789")
os.environ.setdefault("RATE_LIMIT_LOGIN_PER_MINUTE", "1000")
os.environ.setdefault("RATE_LIMIT_REGISTER_PER_HOUR", "1000")
os.environ.setdefault("TRUSTED_PROXIES", "")
os.environ.setdefault("ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from tests.guards import (  # noqa: E402
    UnsafeTestDatabaseError,
    assert_disposable_test_database,
    read_env_file_value,
    verify_connected_database,
)

# The protected application database, resolved BEFORE DATABASE_URL is overridden below
# (environment first, then backend/.env). Passing it explicitly prevents a false
# "collision" after the override and keeps the check meaningful.
# `or ""` matters: passing None would make the guard fall back to `DATABASE_URL`, which by
# then has been overridden to the TEST url — producing a confusing "self collision" instead
# of the accurate "application database is not configured" refusal. An empty string says
# explicitly "there is no application URL", so the guard fails closed with the right reason.
PROTECTED_APP_DB_URL = CONFIGURED_APP_DB_URL or read_env_file_value("DATABASE_URL") or ""

@pytest.fixture(scope="session")
def engine():
    """Validate safety layers, then rebuild a clean schema with the real migrations."""
    try:
        assert_disposable_test_database(TEST_DB_URL, app_url=PROTECTED_APP_DB_URL)
    except UnsafeTestDatabaseError as exc:
        pytest.exit(str(exc), returncode=2)

    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        # Live identity + production marker re-check, now also compared against the
        # application database so an alias trick cannot reach the app database.
        verify_connected_database(conn, app_url=PROTECTED_APP_DB_URL)
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    admin.dispose()

    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    result = subprocess.run(
        ["alembic", "upgrade", "head"], cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"Alembic upgrade failed:\n{result.stdout}\n{result.stderr}"

    eng = create_engine(TEST_DB_URL, pool_pre_ping=True)

    from app.core.db import SessionLocal
    from app.seed import seed

    with SessionLocal() as db:
        seed(db)
    yield eng
    eng.dispose()


@pytest.fixture()
def connection(engine):
    """One outer transaction per test; rolled back at teardown for isolation."""
    conn = engine.connect()
    outer = conn.begin()
    try:
        yield conn
    finally:
        outer.rollback()
        conn.close()


@pytest.fixture()
def session_factory(connection):
    return sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture()
def db_session(session_factory):
    """Session for test setup/assertions; shares the per-test transaction."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_production_get_db(factory):
    """Same commit/rollback contract as app.core.db.get_db, bound to a test factory."""

    def _get_db():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _get_db


@pytest.fixture()
def client(session_factory):
    from app.core.db import get_db
    from app.core.ratelimit import reset_rate_limits
    from app.main import app

    reset_rate_limits()
    app.dependency_overrides[get_db] = make_production_get_db(session_factory)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def live_server(engine):
    """Real uvicorn server on a free loopback port — required for concurrency tests."""
    import uvicorn

    from app.main import app as fastapi_app

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    config = uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=port, log_level="warning", access_log=False, proxy_headers=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn live test server failed to start")

    from app.core.ratelimit import reset_rate_limits

    reset_rate_limits()
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def live_client(live_server):
    """HTTP client bound to the live server (one client per test; threads create their own)."""
    import httpx

    with httpx.Client(base_url=live_server, timeout=30.0) as http_client:
        yield http_client


@pytest.fixture()
def cleanup_phones(engine):
    """Delete users (and their audit rows) created by live-server tests.

    Entries may be given as a 10-digit local number or E.164; both are normalised to
    E.164 because that is how accounts are stored. Without this the DELETE silently
    matched nothing and left committed rows behind, breaking unrelated assertions.
    """
    phones: list[str] = []

    def _normalise(value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) == 10:
            return f"+91{digits}"
        if len(digits) == 12 and digits.startswith("91"):
            return f"+{digits}"
        return value

    yield phones
    if not phones:
        return
    normalised = sorted({_normalise(phone) for phone in phones})
    with engine.begin() as conn:
        ids = [
            row[0]
            for row in conn.execute(
                text("SELECT id FROM users WHERE phone = ANY(:phones)"), {"phones": normalised}
            )
        ]
        if ids:
            conn.execute(text("DELETE FROM audit_logs WHERE actor_user_id = ANY(:ids)"), {"ids": ids})
            conn.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})


@pytest.fixture()
def make_user(db_session):
    """Factory: create a user with an arbitrary role code and hashed password."""
    from app.core.security import hash_password
    from app.models.identity import Role, User, UserRole
    from app.schemas.auth import normalize_phone

    counter = {"n": 0}

    def _make(role_code: str = "CUSTOMER", password: str = "Passw0rd1", phone: str | None = None, active: bool = True):
        counter["n"] += 1
        n = counter["n"]
        phone = phone or f"+9198{n:08d}"
        user = User(
            phone=normalize_phone(phone),
            email=f"user{n}@example.com",
            password_hash=hash_password(password),
            full_name=f"Test User {n}",
            is_active=active,
        )
        db_session.add(user)
        db_session.flush()
        role = db_session.query(Role).filter_by(code=role_code).one()
        db_session.add(UserRole(user_id=user.id, role_id=role.id, granted_by_id=user.id))
        db_session.flush()
        return user, password

    return _make


@pytest.fixture()
def auth_headers(client):
    def _login(phone: str, password: str = "Passw0rd1") -> dict:
        resp = client.post("/api/v1/auth/login", json={"identifier": phone, "password": password})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _login
