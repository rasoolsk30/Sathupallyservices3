"""Lock-order regression tests (review finding: inconsistent database lock order).

Three layers of proof:

A. **Hazard proof** — two real connections execute the *old* inverted sequence
   (token→user vs user→token) with a barrier forcing the interleaving. PostgreSQL
   must abort one transaction with SQLSTATE 40P01. This demonstrates that the
   interleaving genuinely deadlocks, so the ordering matters.

B. **Order assertion** — the SQL actually emitted by each endpoint is captured with a
   SQLAlchemy event listener; the first `FOR UPDATE` statement must target `users`,
   and every token-row lock must come after it.

C. **Endpoint races** — real concurrent HTTP requests on a live uvicorn server for the
   three scenarios in the review. No request may return 5xx; deadlock errors are never
   swallowed, so a 500 would surface here.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
CHANGE = "/api/v1/auth/change-password"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _account(phone: str) -> dict:
    return {
        "full_name": "Lock Order Probe",
        "phone": phone,
        "email": f"{phone}@example.com",
        "password": "Secret123",
        "preferred_language": "en",
    }


def _active_token_hashes(engine, phone: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.token_hash FROM auth_refresh_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE u.phone = :p AND t.revoked_at IS NULL"
            ),
            {"p": _e164(phone)},
        )
        return {r[0] for r in rows}


def _e164(phone: str) -> str:
    """Phone numbers are stored in E.164; SQL assertions must use that form."""
    return phone if phone.startswith("+") else f"+91{phone}"


def _post(base_url: str, path: str, payload: dict, headers: dict | None = None):
    import httpx

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        return client.post(path, json=payload, headers=headers or {})


@pytest.fixture()
def committed_session():
    """A real committing session on the real engine (the concurrency tests need visible rows)."""
    from app.core.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_user_and_token(session, phone: str, token_hash: str) -> tuple[int, int]:
    from app.models.identity import AuthRefreshToken, User

    user = User(phone=phone, password_hash="not-a-real-hash", full_name="Lock Probe")
    session.add(user)
    session.flush()
    token = AuthRefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    session.add(token)
    session.commit()
    return user.id, token.id


def _cleanup(session, user_id: int, phone: str) -> None:
    from app.models.admin import AuditLog
    from app.models.identity import AuthRefreshToken, User

    session.execute(AuthRefreshToken.__table__.delete().where(AuthRefreshToken.user_id == user_id))
    session.execute(AuditLog.__table__.delete().where(AuditLog.actor_user_id == user_id))
    session.execute(User.__table__.delete().where(User.phone == phone))
    session.commit()


# ---------------------------------------------------------------------------
# A. hazard proof
# ---------------------------------------------------------------------------
class TestDeadlockHazardIsReal:
    def test_inverted_lock_order_deadlocks_postgres(self, engine, committed_session):
        """The old refresh path (token→user) vs change-password (user→token) must deadlock."""
        phone = "+919711100001"
        uid, tid = _seed_user_and_token(committed_session, phone, "deadlock-probe-hash-1")
        try:
            barrier = threading.Barrier(2, timeout=15)
            results: dict[str, str] = {}

            def token_then_user():
                with engine.connect() as conn:
                    # deadlock_timeout is superuser-only; PostgreSQL's 1s default applies.
                    conn.execute(text("SET lock_timeout = '10s'"))
                    conn.execute(text("SELECT id FROM auth_refresh_tokens WHERE id = :t FOR UPDATE"), {"t": tid})
                    barrier.wait()
                    try:
                        conn.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": uid})
                        results["token_then_user"] = "ok"
                    except DBAPIError as exc:
                        results["token_then_user"] = _classify(exc)

            def user_then_token():
                with engine.connect() as conn:
                    # deadlock_timeout is superuser-only; PostgreSQL's 1s default applies.
                    conn.execute(text("SET lock_timeout = '10s'"))
                    conn.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": uid})
                    barrier.wait()
                    try:
                        conn.execute(text("SELECT id FROM auth_refresh_tokens WHERE id = :t FOR UPDATE"), {"t": tid})
                        results["user_then_token"] = "ok"
                    except DBAPIError as exc:
                        results["user_then_token"] = _classify(exc)

            threads = [threading.Thread(target=token_then_user), threading.Thread(target=user_then_token)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

            outcomes = sorted(results.values())
            assert "deadlock" in outcomes, (
                "expected PostgreSQL to report a deadlock for the inverted order, got "
                f"{results} — the hazard proof is not exercising a real ABBA cycle"
            )
        finally:
            _cleanup(committed_session, uid, phone)

    def test_uniform_order_never_deadlocks(self, engine, committed_session):
        """With the enforced order (user first everywhere) the same interleaving is serialised."""
        phone = "+919711100002"
        uid, tid = _seed_user_and_token(committed_session, phone, "deadlock-probe-hash-2")
        try:
            results: dict[str, str] = {}
            first_locked = threading.Event()

            def worker(name: str):
                with engine.connect() as conn:
                    conn.execute(text("SET lock_timeout = '15s'"))
                    conn.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": uid})
                    if name == "a":
                        first_locked.set()
                    else:
                        first_locked.wait(timeout=5)
                    conn.execute(text("SELECT id FROM auth_refresh_tokens WHERE id = :t FOR UPDATE"), {"t": tid})
                    results[name] = "ok"

            threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

            assert results == {"a": "ok", "b": "ok"}, results
        finally:
            _cleanup(committed_session, uid, phone)


def _classify(exc: DBAPIError) -> str:
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
        getattr(exc, "orig", None), "pgcode", None
    )
    if sqlstate == "40P01":
        return "deadlock"
    if sqlstate == "55P03":
        return "lock_timeout"
    return f"other:{sqlstate}"


# ---------------------------------------------------------------------------
# B. order assertion on real endpoint SQL
# ---------------------------------------------------------------------------
@pytest.fixture()
def sql_capture():
    from app.core.db import engine as app_engine

    statements: list[str] = []
    lock = threading.Lock()

    def handler(conn, cursor, statement, parameters, context, executemany):
        with lock:
            statements.append(statement)

    event.listen(app_engine, "before_cursor_execute", handler)
    try:
        yield statements
    finally:
        event.remove(app_engine, "before_cursor_execute", handler)


def _lock_targets(statements: list[str]) -> list[str]:
    targets = []
    for stmt in statements:
        upper = stmt.upper()
        if "FOR UPDATE" not in upper and not upper.startswith("UPDATE AUTH_REFRESH_TOKENS"):
            continue
        lowered = stmt.lower()
        if "from users" in lowered or lowered.startswith("update users"):
            targets.append("users")
        elif "auth_refresh_tokens" in lowered:
            targets.append("auth_refresh_tokens")
    return targets


class TestEndpointsUseCanonicalOrder:
    def _setup(self, live_server, cleanup_phones, phone: str):
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201
        login = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"})
        assert login.status_code == 200, login.text
        return login.json()

    def test_refresh_locks_user_before_token(self, live_server, sql_capture, cleanup_phones):
        tokens = self._setup(live_server, cleanup_phones, "9711200001")
        sql_capture.clear()
        resp = _post(live_server, REFRESH, {"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 200, resp.text
        targets = _lock_targets(sql_capture)
        assert targets[:1] == ["users"], f"refresh must lock users first, saw {targets}"
        assert all(t != "users" for t in targets[1:]), f"user lock taken twice / out of order: {targets}"

    def test_refresh_reuse_path_locks_user_before_token(self, live_server, sql_capture, cleanup_phones):
        tokens = self._setup(live_server, cleanup_phones, "9711200002")
        assert _post(live_server, REFRESH, {"refresh_token": tokens["refresh_token"]}).status_code == 200
        sql_capture.clear()
        replay = _post(live_server, REFRESH, {"refresh_token": tokens["refresh_token"]})
        assert replay.status_code == 401
        targets = _lock_targets(sql_capture)
        assert targets[:1] == ["users"], f"reuse path must lock users first, saw {targets}"
        assert all(t != "users" for t in targets[1:]), targets

    def test_change_password_locks_user_before_tokens(self, live_server, sql_capture, cleanup_phones):
        tokens = self._setup(live_server, cleanup_phones, "9711200003")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        sql_capture.clear()
        resp = _post(
            live_server, CHANGE,
            {"current_password": "Secret123", "new_password": "BrandNew456"}, headers,
        )
        assert resp.status_code == 200, resp.text
        targets = _lock_targets(sql_capture)
        assert targets[:1] == ["users"], f"change-password must lock users first, saw {targets}"
        assert all(t != "users" for t in targets[1:]), targets

    def test_logout_locks_user_before_tokens(self, live_server, sql_capture, cleanup_phones):
        tokens = self._setup(live_server, cleanup_phones, "9711200004")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        sql_capture.clear()
        resp = _post(live_server, "/api/v1/auth/logout", {"all_sessions": True}, headers)
        assert resp.status_code == 200, resp.text
        targets = _lock_targets(sql_capture)
        assert targets[:1] == ["users"], f"logout must lock users first, saw {targets}"
        assert all(t != "users" for t in targets[1:]), targets


# ---------------------------------------------------------------------------
# C. endpoint races demanded by the review
# ---------------------------------------------------------------------------
class TestConcurrentReuseAndPasswordChange:
    def test_simultaneous_reuse_and_password_change(self, live_server, engine, cleanup_phones):
        """Reuse detection racing a password change must not deadlock or 5xx."""
        phone = "9711300001"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        login = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
        first = login["refresh_token"]
        seeded = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
        access = seeded["access_token"]

        # Token 'first' is already reused below; rotate once so it becomes a revoked token.
        rotated = _post(live_server, REFRESH, {"refresh_token": first})
        assert rotated.status_code == 200

        pre_race = _active_token_hashes(engine, phone)
        assert pre_race, "expected active sessions before the race"

        barrier = threading.Barrier(2, timeout=15)

        def reuse():
            barrier.wait()
            return _post(live_server, REFRESH, {"refresh_token": first})

        def change():
            barrier.wait()
            return _post(
                live_server, CHANGE,
                {"current_password": "Secret123", "new_password": "BrandNew456"},
                {"Authorization": f"Bearer {access}"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            reuse_future = pool.submit(reuse)
            change_future = pool.submit(change)
            reuse_resp = reuse_future.result()
            change_resp = change_future.result()

        assert reuse_resp.status_code == 401, reuse_resp.text
        assert change_resp.status_code in (200, 401), change_resp.text
        assert reuse_resp.status_code < 500 and change_resp.status_code < 500

        # Token-family revocation must be persistent regardless of interleaving: no session
        # that existed before the race may survive. If the password change finished last, the
        # replacement session it issued is the only token allowed to remain active.
        from app.core.security import hash_refresh_token

        active = _active_token_hashes(engine, phone)
        assert not (active & pre_race), "a pre-race session survived — family revocation was lost"
        if change_resp.status_code == 200:
            allowed = {hash_refresh_token(change_resp.json()["refresh_token"])}
            assert active <= allowed, "unexpected active session after the race"
        else:
            assert active == set()

    def test_simultaneous_reuse_with_two_different_tokens_same_user(self, live_server, engine, cleanup_phones):
        """Two different revoked tokens of the same user reused concurrently."""
        phone = "9711300002"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        t1 = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()["refresh_token"]
        t2 = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()["refresh_token"]
        # Rotate both so each becomes a revoked (reusable) token.
        assert _post(live_server, REFRESH, {"refresh_token": t1}).status_code == 200
        assert _post(live_server, REFRESH, {"refresh_token": t2}).status_code == 200

        barrier = threading.Barrier(2, timeout=15)

        def replay(token: str):
            barrier.wait()
            return _post(live_server, REFRESH, {"refresh_token": token})

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(replay, t1)
            b = pool.submit(replay, t2)
            ra, rb = a.result(), b.result()

        assert {ra.status_code, rb.status_code} == {401}, (ra.text, rb.text)
        for response in (ra, rb):
            assert response.json()["error"]["code"] == "refresh_token_reused"

        with engine.connect() as conn:
            unrevoked = conn.execute(
                text(
                    "SELECT count(*) FROM auth_refresh_tokens t JOIN users u ON u.id = t.user_id "
                    "WHERE u.phone = :p AND t.revoked_at IS NULL"
                ),
                {"p": _e164(phone)},
            ).scalar_one()
            audit_rows = conn.execute(
                text(
                    "SELECT count(*) FROM audit_logs a JOIN users u ON u.id = a.actor_user_id "
                    "WHERE u.phone = :p AND a.action = 'auth.refresh_reuse_detected'"
                ),
                {"p": _e164(phone)},
            ).scalar_one()
        assert unrevoked == 0, "family revocation must persist under concurrent reuse"
        assert audit_rows >= 1

    def test_refresh_and_password_change_race(self, live_server, engine, cleanup_phones):
        """A valid refresh racing a password change: one wins, no deadlock, all sessions revoked."""
        phone = "9711300003"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        login = _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json()
        token = login["refresh_token"]
        access = login["access_token"]
        pre_race = _active_token_hashes(engine, phone)
        assert pre_race, "expected an active session before the race"

        barrier = threading.Barrier(2, timeout=15)

        def refresh_call():
            barrier.wait()
            return _post(live_server, REFRESH, {"refresh_token": token})

        def change_call():
            barrier.wait()
            return _post(
                live_server, CHANGE,
                {"current_password": "Secret123", "new_password": "BrandNew456"},
                {"Authorization": f"Bearer {access}"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            rf = pool.submit(refresh_call)
            cf = pool.submit(change_call)
            refresh_resp, change_resp = rf.result(), cf.result()

        assert refresh_resp.status_code in (200, 401), refresh_resp.text
        assert change_resp.status_code == 200, change_resp.text

        from app.core.security import hash_refresh_token

        active = _active_token_hashes(engine, phone)
        assert not (active & pre_race), "password change must revoke every previously active session"
        # The change's own replacement session is the only token allowed to survive.
        assert active <= {hash_refresh_token(change_resp.json()["refresh_token"])}

    def test_password_change_revokes_every_session_sequentially(self, live_server, engine, cleanup_phones):
        phone = "9711300004"
        cleanup_phones.append(phone)
        assert _post(live_server, REGISTER, _account(phone)).status_code == 201

        sessions = [
            _post(live_server, LOGIN, {"identifier": phone, "password": "Secret123"}).json() for _ in range(3)
        ]
        resp = _post(
            live_server, CHANGE,
            {"current_password": "Secret123", "new_password": "BrandNew456"},
            {"Authorization": f"Bearer {sessions[0]['access_token']}"},
        )
        assert resp.status_code == 200

        # Immediately after the change: exactly the replacement session is active.
        with engine.connect() as conn:
            active_after_change = conn.execute(
                text(
                    "SELECT count(*) FROM auth_refresh_tokens t JOIN users u ON u.id = t.user_id "
                    "WHERE u.phone = :p AND t.revoked_at IS NULL"
                ),
                {"p": _e164(phone)},
            ).scalar_one()
        assert active_after_change == 1, "password change must revoke all but the replacement session"

        # Replaying any pre-change token is refused...
        for session in sessions:
            replay = _post(live_server, REFRESH, {"refresh_token": session["refresh_token"]})
            assert replay.status_code == 401, "pre-change session must be revoked"

        # ...and, by documented policy, reuse detection then revokes the whole family
        # (including the replacement issued by the change).
        with engine.connect() as conn:
            active_after_replay = conn.execute(
                text(
                    "SELECT count(*) FROM auth_refresh_tokens t JOIN users u ON u.id = t.user_id "
                    "WHERE u.phone = :p AND t.revoked_at IS NULL"
                ),
                {"p": _e164(phone)},
            ).scalar_one()
        assert active_after_replay == 0
