"""Authentication/authorization dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AuthError, ForbiddenError
from app.core.ratelimit import client_ip
from app.core.security import decode_access_token
from app.models.identity import Permission, Role, RolePermission, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

# Paths a user may call while a password change is required (bootstrap safety).
PASSWORD_CHANGE_ALLOWED_PATHS = frozenset(
    {
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
        "/api/v1/auth/refresh",
    }
)


def normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


@dataclass
class AuthContext:
    user: User
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)

    def has(self, *codes: str) -> bool:
        return any(c in self.permissions for c in codes)

    @property
    def is_admin_any(self) -> bool:
        return bool(self.permissions & {"admin:dashboard:read", "admin:users:manage"})


def load_auth_context(db: Session, user: User) -> AuthContext:
    role_rows = db.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).scalars().all()
    perm_rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user.id)
        .distinct()
    ).scalars().all()
    return AuthContext(user=user, roles=list(role_rows), permissions=set(perm_rows))


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AuthError("Authentication required.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise AuthError("Access token expired.", code="token_expired")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid access token.", code="invalid_token")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("Account is inactive or does not exist.", code="account_inactive")

    # must_change_password is enforced server-side, not just in the UI: such a session
    # may only inspect itself, change the password, refresh or log out.
    password_change_pending = bool(payload.get("pwd_change_required")) or user.must_change_password
    if password_change_pending and normalize_path(request.url.path) not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise ForbiddenError(
            "Password change required before continuing.", code="password_change_required"
        )

    request.state.user_id = user.id
    return user


def get_auth_context(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthContext:
    return load_auth_context(db, user)


def require_permissions(*codes: str, any_of: bool = False):
    """Dependency factory enforcing backend-side RBAC.

    Usage: dependencies=[Depends(require_permissions("admin:users:read"))]
    or inject: ctx: AuthContext = Depends(require_permissions("booking:create"))
    """

    def checker(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if any_of:
            if not ctx.has(*codes):
                raise ForbiddenError("You do not have permission to perform this action.")
        else:
            missing = [c for c in codes if c not in ctx.permissions]
            if missing:
                raise ForbiddenError(
                    "You do not have permission to perform this action.", details={"missing": missing}
                )
        return ctx

    return checker


def request_meta(request: Request) -> dict:
    return {
        "ip": client_ip(request),
        "user_agent": request.headers.get("user-agent", "")[:300],
    }
