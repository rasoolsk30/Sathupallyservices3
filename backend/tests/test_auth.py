"""Authentication, session security and authorization tests (Milestone 2)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.identity import AuthRefreshToken, User

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

VALID = {
    "full_name": "Ravi Kumar",
    "phone": "9876543210",
    "email": "ravi@example.com",
    "password": "Secret123",
    "preferred_language": "te",
}


def register(client, **overrides):
    payload = {**VALID, **overrides}
    return client.post(REGISTER, json=payload)


class TestRegistration:
    def test_register_success(self, client):
        resp = register(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["user"]["phone"] == "+919876543210"
        assert body["user"]["preferred_language"] == "te"
        assert body["roles"] == ["CUSTOMER"]
        assert body["access_token"] and body["refresh_token"]
        assert body["token_type"] == "bearer"

    def test_register_accepts_local_phone_formats(self, client):
        for idx, phone in enumerate(["09876543211", "9876543212", "+919876543213", "919876543214"]):
            resp = register(client, phone=phone, email=f"f{idx}@example.com")
            assert resp.status_code == 201, (phone, resp.text)

    def test_register_duplicate_phone_conflict(self, client):
        assert register(client).status_code == 201
        resp = register(client, email="other@example.com")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "account_exists"

    def test_register_weak_password_rejected(self, client):
        resp = register(client, password="short1")
        assert resp.status_code == 422
        resp = register(client, password="alllettersonly")
        assert resp.status_code == 422

    def test_register_invalid_phone_rejected(self, client):
        for bad in ["12345", "5876543210", "abcdefghij"]:
            resp = register(client, phone=bad)
            assert resp.status_code == 422, bad

    def test_password_is_hashed_not_stored_plaintext(self, client, db_session):
        register(client)
        user = db_session.execute(select(User).where(User.phone == "+919876543210")).scalar_one()
        assert user.password_hash != VALID["password"]
        assert user.password_hash.startswith("$argon2id$")


class TestLogin:
    def test_login_success_and_me(self, client):
        register(client)
        resp = client.post(LOGIN, json={"identifier": "9876543210", "password": "Secret123"})
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]

        me = client.get(ME, headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["user"]["phone"] == "+919876543210"
        assert "booking:create" in body["permissions"]
        assert "admin:users:read" not in body["permissions"]

    def test_login_with_email(self, client):
        register(client)
        resp = client.post(LOGIN, json={"identifier": "ravi@example.com", "password": "Secret123"})
        assert resp.status_code == 200

    def test_login_wrong_password(self, client):
        register(client)
        resp = client.post(LOGIN, json={"identifier": "9876543210", "password": "WrongPass1"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_credentials"

    def test_login_unknown_user(self, client):
        resp = client.post(LOGIN, json={"identifier": "9999999999", "password": "Whatever1"})
        assert resp.status_code == 401

    def test_lockout_after_repeated_failures(self, client):
        register(client)
        for _ in range(5):
            client.post(LOGIN, json={"identifier": "9876543210", "password": "WrongPass1"})
        resp = client.post(LOGIN, json={"identifier": "9876543210", "password": "Secret123"})
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "account_locked"

    def test_inactive_user_cannot_login(self, client, make_user):
        user, password = make_user(active=False)
        resp = client.post(LOGIN, json={"identifier": user.phone, "password": password})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "account_inactive"

    def test_sql_injection_identifier_is_safe(self, client):
        resp = client.post(LOGIN, json={"identifier": "' OR '1'='1' --", "password": "x"})
        assert resp.status_code in (401, 422)
        assert "Traceback" not in resp.text

    def test_me_requires_token(self, client):
        resp = client.get(ME)
        assert resp.status_code == 401

    def test_me_rejects_garbage_token(self, client):
        resp = client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401


class TestRefreshAndLogout:
    def test_refresh_rotates_and_old_token_dies(self, client):
        tokens = register(client).json()
        first_refresh = tokens["refresh_token"]

        r1 = client.post(REFRESH, json={"refresh_token": first_refresh})
        assert r1.status_code == 200
        second_refresh = r1.json()["refresh_token"]
        assert second_refresh != first_refresh

        # Reuse of the rotated token must fail and revoke the family.
        replay = client.post(REFRESH, json={"refresh_token": first_refresh})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "refresh_token_reused"

        # The replacement token was revoked by the reuse response.
        r2 = client.post(REFRESH, json={"refresh_token": second_refresh})
        assert r2.status_code == 401

    def test_logout_revokes_refresh_token(self, client):
        tokens = register(client).json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        resp = client.post(LOGOUT, json={"refresh_token": tokens["refresh_token"]}, headers=headers)
        assert resp.status_code == 200
        again = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert again.status_code == 401

    def test_logout_all_sessions(self, client):
        tokens = register(client).json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        client.post(LOGOUT, json={"all_sessions": True}, headers=headers)
        again = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert again.status_code == 401


class TestOtpHonesty:
    def test_otp_endpoint_reports_not_configured(self, client):
        resp = client.post("/api/v1/auth/verify-otp", json={"identifier": "9876543210", "otp_code": "123456"})
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "otp_not_configured"


class TestRbacEngine:
    """Unit tests for the permission dependency itself."""

    def _ctx(self, perms: set[str]):
        from app.core.deps import AuthContext

        class FakeUser:
            id = 1

        return AuthContext(user=FakeUser(), roles=[], permissions=perms)

    def test_requires_all_listed_permissions(self):
        from app.core.deps import require_permissions
        from app.core.errors import ForbiddenError

        checker = require_permissions("admin:users:read", "admin:users:manage")
        with pytest.raises(ForbiddenError):
            checker(ctx=self._ctx({"admin:users:read"}))

    def test_any_of_mode(self):
        from app.core.deps import require_permissions

        checker = require_permissions("admin:users:read", "admin:providers:read", any_of=True)
        result = checker(ctx=self._ctx({"admin:providers:read"}))
        assert result is not None

    def test_denies_empty_permissions(self):
        from app.core.deps import require_permissions
        from app.core.errors import ForbiddenError

        checker = require_permissions("admin:settings:manage")
        with pytest.raises(ForbiddenError):
            checker(ctx=self._ctx(set()))
