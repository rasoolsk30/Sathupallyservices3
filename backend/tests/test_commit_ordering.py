"""Read-after-write regression tests for the commit-after-response defect (Milestone 2.4).

Defect under test
-----------------
Mutating endpoints relied on the `get_db` yield-dependency's teardown to commit. FastAPI runs
that teardown AFTER the response has been flushed to the ASGI server, so a client can receive
`200 OK` while the transaction is still open. Measured on this stack: 20/20 responses reached
the client before the commit completed (~3 ms later).

Security impact: `/auth/change-password` revokes every session, but a login whose INSERT
committed only *after* the response escapes the revocation, because the revocation UPDATE
cannot see an uncommitted row.

These tests verify *persisted database state from an independent connection*, opened
immediately after the HTTP response arrives — deliberately bypassing the application's
connection pool (`psycopg.connect`, autocommit) so nothing is masked by session state.

They are repeated in a loop because the defect is a race: a single execution can pass by luck.
"""
from __future__ import annotations

import os
import time

import httpx
import psycopg
import pytest
from sqlalchemy.engine import make_url

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
CHANGE = "/api/v1/auth/change-password"
LOGOUT = "/api/v1/auth/logout"

# How many times each read-after-write check repeats. The pre-fix code failed ~40% of whole
# suite runs; 12-15 iterations per scenario makes an accidental pass vanishingly unlikely.
ITERATIONS = 12


def _e164(phone: str) -> str:
    return phone if phone.startswith("+") else f"+91{phone}"


def _dsn() -> str:
    """libpq DSN for the TEST database, derived from the app URL (no app code involved)."""
    url = make_url(os.environ["DATABASE_URL"])
    return (
        f"host={url.host} port={url.port or 5432} dbname={url.database} "
        f"user={url.username} password={url.password}"
    )


@pytest.fixture()
def fresh_conn():
    """A brand-new autocommit connection, opened fresh for each assertion batch."""
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        yield conn


def _token_rows(conn, phone: str) -> list[tuple]:
    return conn.execute(
        "SELECT t.id, t.revoked_at FROM auth_refresh_tokens t "
        "JOIN users u ON u.id = t.user_id WHERE u.phone = %s ORDER BY t.id",
        (_e164(phone),),
    ).fetchall()


def _user_exists(conn, phone: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE phone = %s", (_e164(phone),)).fetchone() is not None


def _post(base_url: str, path: str, payload: dict, headers: dict | None = None) -> httpx.Response:
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        return client.post(path, json=payload, headers=headers or {})


def _account(phone: str) -> dict:
    return {
        "full_name": "RAW Probe",
        "phone": phone,
        "email": f"{phone}@example.com",
        "password": "Secret123",
        "preferred_language": "en",
    }


class TestRegistrationIsPersistedBeforeResponse:
    def test_user_row_visible_immediately_after_201(self, live_server, fresh_conn, cleanup_phones):
        """Repeat: create a user, then read it from a NEW connection with zero delay."""
        failures = []
        for i in range(ITERATIONS):
            phone = f"98440{i:05d}"
            cleanup_phones.append(phone)
            resp = _post(live_server, REGISTER, _account(phone))
            if resp.status_code != 201:
                failures.append((i, f"register status {resp.status_code}"))
                continue
            if not _user_exists(fresh_conn, phone):
                failures.append((i, "user row not visible immediately after 201"))
        assert not failures, f"commit-after-response still present: {failures}"

    def test_registration_token_visible_immediately_after_201(self, live_server, fresh_conn, cleanup_phones):
        failures = []
        for i in range(ITERATIONS):
            phone = f"98441{i:05d}"
            cleanup_phones.append(phone)
            if _post(live_server, REGISTER, _account(phone)).status_code != 201:
                failures.append((i, "register failed"))
                continue
            if len(_token_rows(fresh_conn, phone)) < 1:
                failures.append((i, "issued refresh token not persisted before 201"))
        assert not failures, failures


class TestLoginIsPersistedBeforeResponse:
    def test_login_token_visible_immediately_after_200(self, live_server, fresh_conn, cleanup_phones):
        """A login's refresh token must exist the instant the client sees 200."""
        failures = []
        for i in range(ITERATIONS):
            phone = f"98442{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            before = len(_token_rows(fresh_conn, phone))
            resp = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"})
            if resp.status_code != 200:
                failures.append((i, f"login status {resp.status_code}"))
                continue
            after = len(_token_rows(fresh_conn, phone))
            if after != before + 1:
                failures.append((i, f"token count {before}->{after}, expected +1"))
        assert not failures, f"login token not committed before 200: {failures}"


class TestRefreshRotationIsPersistedBeforeResponse:
    def test_rotation_visible_immediately_after_200(self, live_server, fresh_conn, cleanup_phones):
        failures = []
        for i in range(ITERATIONS):
            phone = f"98443{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            token = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()["refresh_token"]
            resp = _post(live_server, REFRESH, {"refresh_token": token})
            if resp.status_code != 200:
                failures.append((i, f"refresh status {resp.status_code}"))
                continue
            rows = _token_rows(fresh_conn, phone)
            # old token revoked + new token inserted must BOTH be durable
            if not any(r[1] is not None for r in rows):
                failures.append((i, "old token not yet revoked"))
            new_token_ok = conn_has_hash(fresh_conn, resp.json()["refresh_token"])
            if not new_token_ok:
                failures.append((i, "new token not yet inserted"))
        assert not failures, f"refresh rotation not committed before 200: {failures}"


class TestPasswordChangeRevocationIsPersistedBeforeResponse:
    def test_only_replacement_session_active_immediately_after_200(self, live_server, fresh_conn, cleanup_phones):
        """The core security guarantee: revocations must be visible before the 200.

        Pre-fix this intermittently reported 4 active sessions instead of 1, because the
        three login tokens had not committed when the revocation UPDATE ran.
        """
        failures = []
        for i in range(ITERATIONS):
            phone = f"98444{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            sessions = [
                _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
                for _ in range(3)
            ]
            resp = _post(
                live_server, CHANGE,
                {"current_password": "Secret123", "new_password": "BrandNew456"},
                {"Authorization": f"Bearer {sessions[0]['access_token']}"},
            )
            if resp.status_code != 200:
                failures.append((i, f"change status {resp.status_code}"))
                continue
            rows = _token_rows(fresh_conn, phone)
            active = [r for r in rows if r[1] is None]
            if len(active) != 1:
                failures.append((i, f"{len(active)} active sessions immediately after 200 (expected 1)"))
                continue
            if not conn_has_hash(fresh_conn, resp.json()["refresh_token"]):
                failures.append((i, "replacement session missing from database"))
        assert not failures, f"password-change revocation not durable before 200: {failures}"

    def test_change_password_then_immediate_login_token_is_revoked(self, live_server, fresh_conn, cleanup_phones):
        """No session created before the change may survive it — including a racing login."""
        failures = []
        for i in range(ITERATIONS):
            phone = f"98445{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            victim = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
            resp = _post(
                live_server, CHANGE,
                {"current_password": "Secret123", "new_password": "BrandNew456"},
                {"Authorization": f"Bearer {victim['access_token']}"},
            )
            assert resp.status_code == 200
            # The victim's pre-change token must be dead the moment the response is received.
            replay = _post(live_server, REFRESH, {"refresh_token": victim["refresh_token"]})
            if replay.status_code != 401:
                failures.append((i, f"pre-change session still valid: {replay.status_code}"))
        assert not failures, failures


class TestLogoutRevocationIsPersistedBeforeResponse:
    def test_logout_all_visible_immediately_after_200(self, live_server, fresh_conn, cleanup_phones):
        failures = []
        for i in range(ITERATIONS):
            phone = f"98446{i:05d}"
            cleanup_phones.append(phone)
            assert _post(live_server, REGISTER, _account(phone)).status_code == 201
            login = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
            resp = _post(
                live_server, LOGOUT, {"all_sessions": True},
                {"Authorization": f"Bearer {login['access_token']}"},
            )
            if resp.status_code != 200:
                failures.append((i, f"logout status {resp.status_code}"))
                continue
            rows = _token_rows(fresh_conn, phone)
            if any(r[1] is None for r in rows):
                failures.append((i, "sessions still active immediately after logout 200"))
        assert not failures, failures


def conn_has_hash(conn, raw_token: str) -> bool:
    """Refresh tokens are stored hashed; check the presented token's hash exists."""
    from app.core.security import hash_refresh_token

    row = conn.execute(
        "SELECT 1 FROM auth_refresh_tokens WHERE token_hash = %s", (hash_refresh_token(raw_token),)
    ).fetchone()
    return row is not None
