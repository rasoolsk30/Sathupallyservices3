"""must_change_password review item: enforcement, change flow and session revocation."""
from __future__ import annotations

import pytest
from fastapi import Depends
from sqlalchemy import select

from app.core.deps import get_current_user
from app.models.admin import AuditLog
from app.models.identity import AuthRefreshToken, User

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
CHANGE = "/api/v1/auth/change-password"


@pytest.fixture()
def protected_route():
    """Temporary authenticated route that is NOT on the password-change allowlist."""
    from app.main import app

    def handler(user=Depends(get_current_user)):
        return {"user_id": user.id}

    app.add_api_route("/api/v1/_test/protected", handler, methods=["GET"], name="_test_protected")
    try:
        yield "/api/v1/_test/protected"
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/api/v1/_test/protected"
        ]


def _make_pending(db_session, make_user):
    user, password = make_user(password="Initial123")
    user.must_change_password = True
    db_session.flush()
    return user, password


class TestEnforcement:
    def test_pending_user_can_read_self_and_is_flagged(self, client, db_session, make_user):
        user, password = _make_pending(db_session, make_user)
        login = client.post(LOGIN, json={"identifier": user.phone, "password": password})
        assert login.status_code == 200
        body = login.json()
        assert body["user"]["must_change_password"] is True

        me = client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["user"]["must_change_password"] is True

    def test_pending_user_is_blocked_from_other_endpoints(self, client, db_session, make_user, protected_route):
        user, password = _make_pending(db_session, make_user)
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]

        blocked = client.get(protected_route, headers={"Authorization": f"Bearer {token}"})
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "password_change_required"

    def test_unflagged_user_is_not_blocked(self, client, db_session, make_user, protected_route):
        user, password = make_user(password="Initial123")
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]
        allowed = client.get(protected_route, headers={"Authorization": f"Bearer {token}"})
        assert allowed.status_code == 200

    def test_logout_still_allowed_while_pending(self, client, db_session, make_user):
        user, password = _make_pending(db_session, make_user)
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]
        resp = client.post("/api/v1/auth/logout", json={"all_sessions": True},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


class TestChangePassword:
    def test_change_clears_flag_and_restores_access(self, client, db_session, make_user, protected_route):
        user, password = _make_pending(db_session, make_user)
        login = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        changed = client.post(
            CHANGE, json={"current_password": password, "new_password": "BrandNew456"}, headers=headers
        )
        assert changed.status_code == 200, changed.text
        body = changed.json()
        assert body["user"]["must_change_password"] is False

        fresh = {"Authorization": f"Bearer {body['access_token']}"}
        assert client.get(protected_route, headers=fresh).status_code == 200

        # New password works, old one does not.
        assert client.post(LOGIN, json={"identifier": user.phone, "password": "BrandNew456"}).status_code == 200
        assert client.post(LOGIN, json={"identifier": user.phone, "password": password}).status_code == 401

    def test_change_revokes_previous_sessions(self, client, db_session, make_user):
        user, password = _make_pending(db_session, make_user)
        login = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        body = client.post(
            CHANGE, json={"current_password": password, "new_password": "BrandNew456"}, headers=headers
        ).json()

        # The replacement token issued by the change is valid...
        new_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
        assert new_refresh.status_code == 200, new_refresh.text

        # ...while every pre-change token was revoked.
        old_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert old_refresh.status_code == 401
        assert old_refresh.json()["error"]["code"] == "refresh_token_reused"

        # Documented consequence: presenting a revoked token triggers family revocation,
        # so the session that was just rotated by the change is revoked too.
        after_family_revocation = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": new_refresh.json()["refresh_token"]}
        )
        assert after_family_revocation.status_code == 401

    def test_wrong_current_password_rejected_and_audited(self, client, db_session, make_user):
        user, password = _make_pending(db_session, make_user)
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]

        resp = client.post(
            CHANGE,
            json={"current_password": "WrongCurrent1", "new_password": "BrandNew456"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_credentials"

        actions = db_session.execute(
            select(AuditLog.action).where(AuditLog.actor_user_id == user.id)
        ).scalars().all()
        assert "auth.password_change_failed" in actions

    @pytest.mark.parametrize("weak", ["short1", "alllettersonly", "123456789", "        "])
    def test_weak_new_password_rejected(self, client, db_session, make_user, weak):
        user, password = _make_pending(db_session, make_user)
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]
        resp = client.post(
            CHANGE,
            json={"current_password": password, "new_password": weak},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "weak_password"

    def test_reusing_same_password_rejected(self, client, db_session, make_user):
        user, password = _make_pending(db_session, make_user)
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]
        resp = client.post(
            CHANGE,
            json={"current_password": password, "new_password": password},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "password_unchanged"

    def test_change_requires_authentication(self, client):
        assert client.post(CHANGE, json={"current_password": "x", "new_password": "y1234567"}).status_code == 401

    def test_password_is_rehashed_with_argon2(self, client, db_session, make_user):
        user, password = _make_pending(db_session, make_user)
        token = client.post(LOGIN, json={"identifier": user.phone, "password": password}).json()["access_token"]
        client.post(CHANGE, json={"current_password": password, "new_password": "BrandNew456"},
                    headers={"Authorization": f"Bearer {token}"})
        refreshed = db_session.execute(select(User).where(User.id == user.id)).scalar_one()
        db_session.refresh(refreshed)
        assert refreshed.password_hash.startswith("$argon2id$")
        assert refreshed.must_change_password is False

