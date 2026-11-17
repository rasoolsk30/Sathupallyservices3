"""Security-state persistence regression tests (Milestone 2.5 / R2.3).

Two behaviours are proven here:

A. SUCCESS PATH — when `_commit_security_state()` commits, the security state (failed-login
   counter, account lock, session revocation, audit row) really is in PostgreSQL *before* the
   client receives the rejection. Verified from an independent `psycopg` autocommit
   connection, i.e. not the application's session.

B. FAILURE PATH — when that commit fails, the client must NOT receive the ordinary
   authentication rejection. It must receive a generic persistence failure that leaks no SQL,
   credentials, driver details or stack traces, and the security state must be rolled back.

These run against the live uvicorn server (`live_server`) because that path performs real
commits; the in-process `client` fixture keeps everything inside an outer transaction and
cannot show durability.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import httpx
import psycopg
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import make_url

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
CHANGE = "/api/v1/auth/change-password"

ITERATIONS = 6
LEAK_MARKERS = ("psql", "postgresql", "password", "INSERT", "SELECT", "Traceback", "sqlalchemy", "psycopg", "user_id", "users")


def _e164(phone: str) -> str:
    return phone if phone.startswith("+") else f"+91{phone}"


def _dsn() -> str:
    url = make_url(os.environ["DATABASE_URL"])
    return (
        f"host={url.host} port={url.port or 5432} dbname={url.database} "
        f"user={url.username} password={url.password}"
    )


@pytest.fixture()
def fresh_conn():
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        yield conn


@contextmanager
def commit_failure(exc):
    """Make every Session.commit() raise `exc` for the duration of the block.

    The live uvicorn server runs in a thread of this process, so patching the class also
    affects the request under test. Restored in `finally` so fixture cleanup is unaffected.
    """
    from sqlalchemy.orm import Session

    original = Session.commit
    state = {"calls": 0}

    def boom(self, *a, **k):  # noqa: ANN001
        state["calls"] += 1
        raise exc

    Session.commit = boom
    try:
        yield state
    finally:
        Session.commit = original


def _post(base_url: str, path: str, payload: dict, headers: dict | None = None) -> httpx.Response:
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        return c.post(path, json=payload, headers=headers or {})


def _account(phone: str) -> dict:
    return {
        "full_name": "Sec State",
        "phone": phone,
        "email": f"{phone}@example.com",
        "password": "Secret123",
        "preferred_language": "en",
    }


def _failed_count(conn, phone: str) -> int:
    row = conn.execute("SELECT failed_login_count FROM users WHERE phone = %s", (_e164(phone),)).fetchone()
    return row[0] if row else -1


def _locked_until(conn, phone: str):
    return conn.execute("SELECT locked_until FROM users WHERE phone = %s", (_e164(phone),)).fetchone()[0]


def _active_sessions(conn, phone: str) -> int:
    return conn.execute(
        "SELECT count(*) FROM auth_refresh_tokens t JOIN users u ON u.id = t.user_id "
        "WHERE u.phone = %s AND t.revoked_at IS NULL",
        (_e164(phone),),
    ).fetchone()[0]


def _audit_rows(conn, phone: str, action: str) -> int:
    return conn.execute(
        "SELECT count(*) FROM audit_logs a JOIN users u ON u.id = a.actor_user_id "
        "WHERE u.phone = %s AND a.action = %s",
        (_e164(phone), action),
    ).fetchone()[0]


def _assert_no_leak(resp: httpx.Response) -> None:
    body = resp.text
    lowered = body.lower()
    for marker in LEAK_MARKERS:
        assert marker.lower() not in lowered, f"response leaked {marker!r}: {body}"
    assert "at 0x" not in body and ".py" not in body


class TestSecurityStatePersistedOnSuccess:
    def test_failed_login_counter_committed_before_401(self, live_server, fresh_conn, cleanup_phones):
        """Repeat: counter and audit row must be readable the instant the 401 arrives."""
        failures = []
        for i in range(ITERATIONS):
            phone = f"98550{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            resp = _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass9"})
            if resp.status_code != 401:
                failures.append((i, f"expected 401, got {resp.status_code}"))
                continue
            if resp.json()["error"]["code"] != "invalid_credentials":
                failures.append((i, "unexpected error code"))
            count = _failed_count(fresh_conn, phone)
            if count != 1:
                failures.append((i, f"failed_login_count={count} immediately after 401, expected 1"))
            if _audit_rows(fresh_conn, phone, "auth.login_failed") != 1:
                failures.append((i, "audit row for auth.login_failed missing"))
        assert not failures, f"security state not committed before the rejection: {failures}"

    def test_account_lock_committed_before_locked_response(self, live_server, fresh_conn, cleanup_phones):
        """The lockout (a security control) must be durable, not lost with the response."""
        failures = []
        for i in range(3):
            phone = f"98551{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            for _ in range(5):
                _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass9"})
            if _locked_until(fresh_conn, phone) is None:
                failures.append((i, "locked_until not persisted after 5 failed logins"))
            # By design the counter resets to 0 at the moment the lock engages
            # (auth.py: `locked.failed_login_count = 0` when just_locked); the durable
            # evidence of the lockout is locked_until, not the counter.
            if _failed_count(fresh_conn, phone) != 0:
                failures.append((i, f"failed_login_count={_failed_count(fresh_conn, phone)}, expected 0 after lock engages"))
            # A correct password must now be refused because the lock is durable.
            resp = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"})
            if resp.status_code not in (423, 401):
                failures.append((i, f"locked account returned {resp.status_code}"))
        assert not failures, failures

    def test_refresh_reuse_revocation_committed_before_401(self, live_server, fresh_conn, cleanup_phones):
        """Family revocation on token reuse must survive the 401 that reports it."""
        failures = []
        for i in range(3):
            phone = f"98552{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            first = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
            # rotate once so the original token is now "used"
            rotated = _post(live_server, REFRESH, {"refresh_token": first["refresh_token"]})
            if rotated.status_code != 200:
                failures.append((i, f"rotation failed {rotated.status_code}"))
                continue
            reuse = _post(live_server, REFRESH, {"refresh_token": first["refresh_token"]})
            if reuse.status_code != 401 or reuse.json()["error"]["code"] != "refresh_token_reused":
                failures.append((i, f"reuse not reported: {reuse.status_code} {reuse.text[:80]}"))
                continue
            active = _active_sessions(fresh_conn, phone)
            if active != 0:
                failures.append((i, f"{active} sessions still active immediately after reuse revocation"))
        assert not failures, failures


class TestCommitFailureIsNotDisguisedAsAuthRejection:
    """The review finding: a failed commit must never be reported as a normal 401."""

    def test_failed_login_returns_503_not_401_when_commit_fails(self, live_server, cleanup_phones):
        phone = "9856000001"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        with commit_failure(OperationalError("BEGIN", {}, Exception("connection to server lost"))):
            resp = _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass9"})

        assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.text[:200]}"
        assert resp.status_code != 401, "auth rejection reported although security state was not persisted"
        assert resp.json()["error"]["code"] == "security_state_not_persisted"
        _assert_no_leak(resp)

    def test_commit_failure_rolls_back_security_state(self, live_server, fresh_conn, cleanup_phones):
        """After a failed commit the counter must not be half-applied."""
        phone = "9856000002"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        with commit_failure(OperationalError("BEGIN", {}, Exception("disk full"))):
            resp = _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass9"})
        assert resp.status_code == 503

        # The increment was discarded, not silently kept-and-lost.
        assert _failed_count(fresh_conn, phone) == 0
        assert _audit_rows(fresh_conn, phone, "auth.login_failed") == 0

        # And the system still works once the database recovers.
        ok = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"})
        assert ok.status_code == 200, f"login broken after injected commit failure: {ok.status_code}"

    def test_refresh_reuse_returns_503_not_reuse_401_when_commit_fails(self, live_server, fresh_conn, cleanup_phones):
        """We must not claim 'all sessions revoked' if the revocation did not commit."""
        phone = "9856000003"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201
        first = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
        assert _post(live_server, REFRESH, {"refresh_token": first["refresh_token"]}).status_code == 200

        with commit_failure(OperationalError("BEGIN", {}, Exception("connection reset"))):
            resp = _post(live_server, REFRESH, {"refresh_token": first["refresh_token"]})

        assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json()["error"]["code"] == "security_state_not_persisted"
        _assert_no_leak(resp)
        # Sessions were NOT reported as revoked, and indeed remain active.
        assert _active_sessions(fresh_conn, phone) >= 1

    def test_change_password_wrong_current_returns_503_when_commit_fails(self, live_server, cleanup_phones):
        phone = "9856000004"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201
        login = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()

        with commit_failure(OperationalError("BEGIN", {}, Exception("server closed the connection"))):
            resp = _post(
                live_server, CHANGE,
                {"current_password": "Nope12345", "new_password": "BrandNew456"},
                {"Authorization": f"Bearer {login['access_token']}"},
            )

        assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json()["error"]["code"] == "security_state_not_persisted"
        _assert_no_leak(resp)

    def test_unexpected_commit_exception_does_not_leak_internals(self, live_server, cleanup_phones):
        """A non-SQLAlchemy failure must still be contained by the generic handler."""
        phone = "9856000005"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        with commit_failure(RuntimeError("secret dsn postgresql://ssh_app:pw@host/db")):
            resp = _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass9"})

        assert resp.status_code == 503
        assert resp.status_code != 401
        _assert_no_leak(resp)
        assert "secret dsn" not in resp.text.lower()


class TestOriginalErrorPreservedOnlyOnSuccess:
    def test_original_code_preserved_when_commit_succeeds(self, live_server, cleanup_phones):
        """Guard against over-correction: the real 401 must still come through normally."""
        phone = "9856000006"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201
        resp = _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass9"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_credentials"
        assert resp.json()["error"]["message"] == "Invalid credentials."
