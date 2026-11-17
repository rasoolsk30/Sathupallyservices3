"""Regression tests for the four defects found during independent M2 review.

Each test is written to FAIL on the pre-fix code and PASS on the fixed code:

1. Failed-login counters / lockout were mutated and then discarded by the rollback
   that the database dependency performs when an AuthError is raised.
2. Refresh-token reuse detection revoked the token family and then discarded the
   revocation with the same rollback.
3. The production safety check compared only the literal uppercase "CHANGE_ME",
   so lowercase and other development credentials slipped through.
4. X-Forwarded-For was trusted from any client, allowing spoofed addresses.

The `client` fixture uses production commit/rollback semantics, which is what the
old harness lacked — that is why these bugs were previously invisible to the suite.
"""
from __future__ import annotations

import types

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.ratelimit import client_ip, reset_rate_limits
from app.models.admin import AuditLog
from app.models.identity import AuthRefreshToken, User
from tests.conftest import make_production_get_db

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"

STRONG_DB = "postgresql+psycopg://svc_user:kR7#mQ2xL9vT4wZ8@db.internal:5432/sathupally"
STRONG_JWT = "n8Qp2Zr7Xc4Vb1Mn6Ty3Uw9Kj5Hg0Fd2Sa7Lk4Jh"

ACCOUNT = {
    "full_name": "Lockout Probe",
    "phone": "9848012345",
    "email": "probe@example.com",
    "password": "Secret123",
    "preferred_language": "en",
}


def _fresh(session_factory):
    return session_factory()


# ---------------------------------------------------------------------------
# Finding 1 — failed-login counter and lockout must survive rollback
# ---------------------------------------------------------------------------
class TestFinding1LoginAttemptPersistence:
    def test_failed_attempt_counter_persists_across_requests(self, client, session_factory):
        assert client.post(REGISTER, json=ACCOUNT).status_code == 201

        for _ in range(3):
            assert client.post(LOGIN, json={"identifier": ACCOUNT["phone"], "password": "WrongPass1"}).status_code == 401

        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            assert user.failed_login_count == 3, "failed-login counter was rolled back"
            assert user.locked_until is None

    def test_lockout_is_enforced_after_five_failures(self, client, session_factory):
        assert client.post(REGISTER, json=ACCOUNT).status_code == 201
        for _ in range(5):
            resp = client.post(LOGIN, json={"identifier": ACCOUNT["phone"], "password": "WrongPass1"})
            assert resp.status_code == 401

        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            assert user.locked_until is not None, "lockout was rolled back"
            assert user.failed_login_count == 0

        blocked = client.post(LOGIN, json={"identifier": ACCOUNT["phone"], "password": ACCOUNT["password"]})
        assert blocked.status_code == 423, "correct password must be refused while locked"
        assert blocked.json()["error"]["code"] == "account_locked"

    def test_lockout_expiry_allows_login_again(self, client, session_factory):
        from datetime import datetime, timedelta, timezone

        assert client.post(REGISTER, json=ACCOUNT).status_code == 201
        for _ in range(5):
            client.post(LOGIN, json={"identifier": ACCOUNT["phone"], "password": "WrongPass1"})

        # Simulate the lockout window elapsing.
        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

        ok = client.post(LOGIN, json={"identifier": ACCOUNT["phone"], "password": ACCOUNT["password"]})
        assert ok.status_code == 200
        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            assert user.locked_until is None and user.failed_login_count == 0

    def test_security_events_are_audited_and_persisted(self, client, session_factory):
        assert client.post(REGISTER, json=ACCOUNT).status_code == 201
        for _ in range(5):
            client.post(LOGIN, json={"identifier": ACCOUNT["phone"], "password": "WrongPass1"})

        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            actions = db.execute(select(AuditLog.action).where(AuditLog.actor_user_id == user.id)).scalars().all()
            assert actions.count("auth.login_failed") == 5, actions
            assert actions.count("auth.account_locked") == 1, actions

    def test_dependency_contract_rolls_back_but_keeps_explicit_commits(self, session_factory):
        """Proves the mechanism the two fixes rely on."""
        gen = make_production_get_db(session_factory)()
        db = next(gen)
        db.add(User(phone="+919000000001", password_hash="x", full_name="Committed Probe"))
        db.commit()  # explicit security-state commit
        db.add(User(phone="+919000000002", password_hash="x", full_name="Rolled Back Probe"))
        db.flush()
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("boom"))

        with _fresh(session_factory) as check:
            assert check.execute(select(User).where(User.phone == "+919000000001")).scalar_one_or_none() is not None
            assert check.execute(select(User).where(User.phone == "+919000000002")).scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Finding 2 — refresh-token family revocation must be committed
# ---------------------------------------------------------------------------
class TestFinding2RefreshReuseRevocation:
    def test_reuse_revokes_family_and_persists(self, client, session_factory):
        tokens = client.post(REGISTER, json=ACCOUNT).json()
        first_refresh = tokens["refresh_token"]

        r1 = client.post(REFRESH, json={"refresh_token": first_refresh})
        assert r1.status_code == 200
        second_refresh = r1.json()["refresh_token"]

        replay = client.post(REFRESH, json={"refresh_token": first_refresh})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "refresh_token_reused"

        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            rows = db.execute(select(AuthRefreshToken).where(AuthRefreshToken.user_id == user.id)).scalars().all()
            assert rows, "expected refresh-token rows"
            assert all(r.revoked_at is not None for r in rows), "family revocation was rolled back"

        # The rotated token must also be dead: revocation is permanent.
        after = client.post(REFRESH, json={"refresh_token": second_refresh})
        assert after.status_code == 401

    def test_reuse_event_is_audited(self, client, session_factory):
        tokens = client.post(REGISTER, json=ACCOUNT).json()
        client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})

        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            actions = db.execute(select(AuditLog.action).where(AuditLog.actor_user_id == user.id)).scalars().all()
            assert "auth.refresh_reuse_detected" in actions, actions


# ---------------------------------------------------------------------------
# Finding 3 — production safety must reject development credentials
# ---------------------------------------------------------------------------
def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


class TestFinding3ProductionSafety:
    @pytest.mark.parametrize(
        "db_url",
        [
            "postgresql+psycopg://ssh_app:CHANGE_ME@db.example.net:5432/sathupally",       # original uppercase default
            "postgresql+psycopg://ssh_app:change_me@db.example.net:5432/sathupally",       # lowercase variant
            "postgresql+psycopg://ssh_app:Change_Me@db.example.net:5432/sathupally",       # mixed case
            "postgresql+psycopg://ssh_app:dev_local_only_change_me@db.example.net/sathupally",  # dev default
            "postgresql+psycopg://ssh_app:DEV_LOCAL_ONLY_CHANGE_ME@db.example.net/sathupally",
            "postgresql+psycopg://ssh_app:postgres@db.example.net/sathupally",             # common weak default
            "postgresql+psycopg://ssh_app:SuperSecretPassw0rd@db.example.net/sathupally",  # contains "password"
            "postgresql+psycopg://ssh_app:short1@db.example.net/sathupally",               # too short
            "postgresql+psycopg://ssh_app@db.example.net/sathupally",                      # no password at all
        ],
    )
    def test_production_rejects_development_database_credentials(self, db_url):
        s = _settings(env="production", database_url=db_url, jwt_secret=STRONG_JWT)
        with pytest.raises(RuntimeError, match="PRODUCTION SAFETY CHECK FAILED"):
            s.assert_production_safe()
        assert any("DATABASE_URL" in p for p in s.production_problems())

    @pytest.mark.parametrize(
        "jwt_secret",
        [
            "dev-only-insecure-secret-change-me",
            "short-secret",
            "CHANGEME-0123456789-0123456789-0123456789",
            "an-example-secret-0123456789-0123456789",
        ],
    )
    def test_production_rejects_weak_jwt_secrets(self, jwt_secret):
        s = _settings(env="production", database_url=STRONG_DB, jwt_secret=jwt_secret)
        with pytest.raises(RuntimeError, match="PRODUCTION SAFETY CHECK FAILED"):
            s.assert_production_safe()
        assert any("JWT_SECRET" in p for p in s.production_problems())

    def test_production_accepts_strong_configuration(self):
        s = _settings(env="production", database_url=STRONG_DB, jwt_secret=STRONG_JWT)
        assert s.production_problems() == []
        s.assert_production_safe()  # must not raise

    def test_env_matching_is_case_insensitive(self):
        s = _settings(env="  ProDuction ", database_url="postgresql+psycopg://u:change_me@h/db", jwt_secret=STRONG_JWT)
        assert s.is_production is True
        with pytest.raises(RuntimeError):
            s.assert_production_safe()

    def test_development_allows_local_defaults(self):
        s = _settings(env="development", database_url="postgresql+psycopg://ssh_app:dev_local_only_change_me@127.0.0.1/sathupally",
                      jwt_secret="dev-only-insecure-secret-change-me")
        assert s.production_problems() == []
        s.assert_production_safe()  # must not raise outside production

    def test_unparseable_database_url_is_rejected(self):
        s = _settings(env="production", database_url="not-a-database-url", jwt_secret=STRONG_JWT)
        assert any("parseable" in p for p in s.production_problems())


# ---------------------------------------------------------------------------
# Finding 4 — X-Forwarded-For must not be trusted blindly
# ---------------------------------------------------------------------------
class FakeRequest:
    def __init__(self, host: str, headers: dict | None = None):
        self.client = types.SimpleNamespace(host=host)
        self.headers = headers or {}


class TestFinding4ClientIp:
    def test_forwarded_for_ignored_when_no_trusted_proxy_configured(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "")
        reset_rate_limits()
        req = FakeRequest("203.0.113.50", {"x-forwarded-for": "1.2.3.4"})
        assert client_ip(req) == "203.0.113.50"

    def test_forwarded_for_ignored_from_untrusted_peer(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
        reset_rate_limits()
        req = FakeRequest("203.0.113.50", {"x-forwarded-for": "10.9.9.9, 1.2.3.4"})
        assert client_ip(req) == "203.0.113.50", "untrusted peer must not be able to set its own IP"

    def test_forwarded_for_honoured_from_trusted_proxy(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
        reset_rate_limits()
        req = FakeRequest("10.0.0.5", {"x-forwarded-for": "198.51.100.7, 10.0.0.9"})
        assert client_ip(req) == "198.51.100.7"

    def test_leftmost_spoofed_entry_is_not_used(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
        reset_rate_limits()
        req = FakeRequest("10.0.0.5", {"x-forwarded-for": "6.6.6.6, 198.51.100.7"})
        assert client_ip(req) == "198.51.100.7"

    def test_all_hops_trusted_falls_back_to_earliest(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
        reset_rate_limits()
        req = FakeRequest("10.0.0.5", {"x-forwarded-for": "10.1.1.1, 10.2.2.2"})
        assert client_ip(req) == "10.1.1.1"

    def test_malformed_forwarded_entries_are_ignored(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
        reset_rate_limits()
        req = FakeRequest("10.0.0.5", {"x-forwarded-for": "not-an-ip, 198.51.100.7"})
        assert client_ip(req) == "198.51.100.7"

    def test_ipv6_bracketed_form_parsed(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "::1/128")
        reset_rate_limits()
        req = FakeRequest("::1", {"x-forwarded-for": "[2001:db8::5]:443"})
        assert client_ip(req) == "2001:db8::5"

    def test_invalid_trusted_proxy_entries_do_not_break_resolution(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "bogus-entry, 10.0.0.0/8")
        reset_rate_limits()
        req = FakeRequest("10.0.0.5", {"x-forwarded-for": "198.51.100.7"})
        assert client_ip(req) == "198.51.100.7"

    def test_audit_ip_ignores_spoofed_header_end_to_end(self, client, session_factory):
        """ASGI-level proof: a spoofed X-Forwarded-For never reaches the audit trail."""
        assert client.post(REGISTER, json=ACCOUNT).status_code == 201
        resp = client.post(
            LOGIN,
            json={"identifier": ACCOUNT["phone"], "password": ACCOUNT["password"]},
            headers={"X-Forwarded-For": "6.6.6.6"},
        )
        assert resp.status_code == 200
        with _fresh(session_factory) as db:
            user = db.execute(select(User).where(User.phone == "+919848012345")).scalar_one()
            ip = db.execute(
                select(AuditLog.ip_address).where(AuditLog.actor_user_id == user.id, AuditLog.action == "auth.login")
            ).scalars().one()
            assert ip == "testclient", f"audit stored spoofed ip {ip!r}"

    def test_missing_forwarded_header_uses_peer(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
        reset_rate_limits()
        assert client_ip(FakeRequest("10.0.0.5")) == "10.0.0.5"
