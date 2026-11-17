"""Concurrency regression tests against a REAL uvicorn server and real PostgreSQL.

Each request gets its own database connection, so these tests exercise actual
PostgreSQL row-level locking rather than the savepoint-shared test session.

Defects these tests were written to catch:

* Lost updates on `users.failed_login_count` when several failed logins run
  concurrently (read-modify-write without `SELECT … FOR UPDATE`).
* Two simultaneous refreshes of the same refresh token both succeeding (rotation
  without row locking), which would mint two valid sessions from one token.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import select, text

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"

CONCURRENT_WORKERS = 8


def _account(phone: str) -> dict:
    return {
        "full_name": "Concurrency Probe",
        "phone": phone,
        "email": f"{phone}@example.com",
        "password": "Secret123",
        "preferred_language": "en",
    }


def _post(base_url: str, path: str, payload: dict) -> httpx.Response:
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        return client.post(path, json=payload)


class TestConcurrentFailedLogins:
    def test_no_lost_updates_on_failed_login_counter(self, live_server, engine, cleanup_phones, monkeypatch):
        from app.api.v1 import auth as auth_module

        # Raise the threshold so every attempt is a plain increment (no lockout reset).
        monkeypatch.setattr(auth_module, "LOCKOUT_THRESHOLD", 1000)

        phone = "9900010001"
        cleanup_phones.append("+919900010001")
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as pool:
            responses = list(
                pool.map(
                    lambda _: _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass1"}),
                    range(CONCURRENT_WORKERS),
                )
            )

        assert all(r.status_code == 401 for r in responses), [r.status_code for r in responses]

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT failed_login_count FROM users WHERE phone = :p"), {"p": "+919900010001"}
            ).scalar_one()
        assert count == CONCURRENT_WORKERS, (
            f"expected {CONCURRENT_WORKERS} serialised increments, got {count} — lost update under concurrency"
        )

    def test_lockout_fires_exactly_once_under_concurrency(self, live_server, engine, cleanup_phones):
        phone = "9900010002"
        cleanup_phones.append("+919900010002")
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        with ThreadPoolExecutor(max_workers=10) as pool:
            responses = list(
                pool.map(
                    lambda _: _post(live_server, LOGIN, {"identifier": phone, "password": "WrongPass1"}),
                    range(10),
                )
            )

        statuses = sorted(r.status_code for r in responses)
        assert statuses.count(401) == 5, f"expected exactly 5 counted failures, got {statuses}"
        assert statuses.count(423) == 5, f"expected the remaining 5 to see the lock, got {statuses}"

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT locked_until, failed_login_count FROM users WHERE phone = :p"),
                {"p": "+919900010002"},
            ).one()
            locked_audits = conn.execute(
                text(
                    "SELECT count(*) FROM audit_logs a JOIN users u ON u.id = a.actor_user_id "
                    "WHERE u.phone = :p AND a.action = 'auth.account_locked'"
                ),
                {"p": "+919900010002"},
            ).scalar_one()
        assert row.locked_until is not None
        assert row.failed_login_count == 0
        assert locked_audits == 1, f"lockout must be recorded exactly once, saw {locked_audits}"

        blocked = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"})
        assert blocked.status_code == 423


class TestConcurrentRefresh:
    def test_simultaneous_refresh_yields_exactly_one_success(self, live_server, engine, cleanup_phones):
        phone = "9900010003"
        cleanup_phones.append("+919900010003")
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        login = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"})
        assert login.status_code == 200
        refresh_token = login.json()["refresh_token"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_post, live_server, REFRESH, {"refresh_token": refresh_token}) for _ in range(2)
            ]
            results = [f.result() for f in futures]

        statuses = sorted(r.status_code for r in results)
        assert statuses == [200, 401], f"exactly one refresh must win, got {statuses}"

        loser = next(r for r in results if r.status_code == 401)
        assert loser.json()["error"]["code"] == "refresh_token_reused"

        # The winning response's token must also be dead afterwards (family revoked).
        winner_token = next(r for r in results if r.status_code == 200).json()["refresh_token"]
        after = _post(live_server, REFRESH, {"refresh_token": winner_token})
        assert after.status_code == 401

        with engine.connect() as conn:
            unrevoked = conn.execute(
                text(
                    "SELECT count(*) FROM auth_refresh_tokens t JOIN users u ON u.id = t.user_id "
                    "WHERE u.phone = :p AND t.revoked_at IS NULL"
                ),
                {"p": "+919900010003"},
            ).scalar_one()
        assert unrevoked == 0, "every token in the family must be revoked after reuse detection"

    def test_many_simultaneous_refreshes_revoke_family_once(self, live_server, engine, cleanup_phones):
        phone = "9900010004"
        cleanup_phones.append("+919900010004")
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201
        token = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()["refresh_token"]

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(
                pool.map(lambda _: _post(live_server, REFRESH, {"refresh_token": token}), range(6))
            )

        statuses = sorted(r.status_code for r in results)
        assert statuses.count(200) == 1, f"only one rotation may win, got {statuses}"
        assert statuses.count(401) == 5, statuses

        with engine.connect() as conn:
            reuse_audits = conn.execute(
                text(
                    "SELECT count(*) FROM audit_logs a JOIN users u ON u.id = a.actor_user_id "
                    "WHERE u.phone = :p AND a.action = 'auth.refresh_reuse_detected'"
                ),
                {"p": "+919900010004"},
            ).scalar_one()
        assert reuse_audits >= 1


class TestSerialisedRotationStillWorks:
    def test_sequential_refresh_chain_is_healthy(self, live_server, cleanup_phones):
        phone = "9900010005"
        cleanup_phones.append("+919900010005")
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201
        token = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()["refresh_token"]

        for _ in range(3):
            resp = _post(live_server, REFRESH, {"refresh_token": token})
            assert resp.status_code == 200, resp.text
            token = resp.json()["refresh_token"]
