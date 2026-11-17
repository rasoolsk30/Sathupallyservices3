"""Authentication router: register, login, refresh, logout, password change, me.

Concurrency and durability
--------------------------
The request-scoped database dependency commits on success and ROLLS BACK on any
exception. Two consequences shape this module:

1. Security state that must survive a rejected request (failed-attempt counters,
   lockouts, token-family revocations) is committed explicitly via
   `_commit_security_state()` **before** the error is raised.

2. Counter mutation and token rotation are read-modify-write cycles that are only
   correct under PostgreSQL row-level locking. `SELECT … FOR UPDATE` is taken on the
   user row before touching the attempt counter, and on the refresh-token row before
   rotating or deciding that a token was reused. Without the locks, concurrent failed
   logins lose increments and two simultaneous refreshes can both succeed.

LOCK ORDER INVARIANT (enforced, tested):
    every transaction that touches both lock classes takes the USER row first and
    refresh-token rows second. Operations that mutate token rows but never take the
    user lock are still made to take it, so there is exactly one global order and no
    transaction can hold a token lock while waiting for a user lock.

    A previous revision violated this: `/refresh` locked the token row first and only
    then locked the user row for reuse detection, while `/change-password` locked the
    user first and then the token rows — an ABBA cycle that PostgreSQL resolves by
    aborting one transaction with `deadlock detected` (SQLSTATE 40P01). Deadlocks are
    never caught or suppressed here; they cannot occur because the order is uniform.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import settings
from app.core.db import commit_or_raise, get_db
from app.core.deps import AuthContext, get_auth_context, get_current_user, load_auth_context, request_meta
from app.core.errors import AppError, AuthError, SecurityStateNotPersistedError, ConflictError, ServiceUnavailableError, ValidationAppError
from app.core.ratelimit import check_rate_limit, client_ip
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    validate_password,
    verify_password,
)
from app.models.customer import CustomerPreference
from app.models.identity import AuthRefreshToken, CustomerProfile, Role, User, UserRole
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    VerifyOtpRequest,
    normalize_phone,
)
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("ssh.auth")

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _commit_security_state(db: Session, error: AppError) -> NoReturn:
    """Persist security-critical state, then raise the intended rejection.

    The dependency rolls back on exceptions, so anything that must outlive a rejected
    request (attempt counters, lockouts, revocations, audit rows) is committed first.

    Failure rule (R2.3): if that commit fails, the ORIGINAL auth error must NOT be raised.
    Returning `401 invalid_credentials` would assert that the failed-login counter and
    audit row were recorded when they were discarded, which hides brute-force attempts and
    leaves lockouts untriggered. Instead we roll back and surface a generic persistence
    failure (503 `security_state_not_persisted`) through the AppError envelope. That error
    carries no SQL, credentials, driver detail or stack trace — the cause is logged
    server-side only.
    """
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:  # pragma: no cover - rollback of a dead connection
            log.exception("Rollback failed after security-state commit error")
        log.exception("Could not persist security state before raising %s", error.code)
        raise SecurityStateNotPersistedError() from None
    raise error


def _lock_user_row(db: Session, user_id: int) -> User | None:
    """Canonical lock step 1 — the USER row. Always acquired before token rows."""
    return db.execute(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _lock_token_row(db: Session, token_id: int) -> AuthRefreshToken | None:
    """Canonical lock step 2 — a single refresh-token row (only after the user lock)."""
    return db.execute(
        select(AuthRefreshToken)
        .where(AuthRefreshToken.id == token_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _locked_user(db: Session, user_id: int) -> User:
    """Re-read the user row under a PostgreSQL row lock (serialises attempt counting).

    `populate_existing()` is essential: the row was already loaded earlier in this
    request, and SQLAlchemy would otherwise return the STALE identity-map instance
    after the lock is acquired, silently discarding the concurrent increment made by
    the transaction we just waited for. With it, the locked read reflects the value
    committed by the previous holder of the lock.
    """
    return db.execute(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()


def _issue_tokens(db: Session, user: User, request: Request, ctx: AuthContext | None = None) -> TokenResponse:
    extra = {"pwd_change_required": True} if user.must_change_password else None
    access, _expires = create_access_token(user.id, extra=extra)
    raw_refresh = new_refresh_token()
    now = _now()
    db.add(
        AuthRefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=now + timedelta(days=settings.refresh_token_days),
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:300] or None,
        )
    )
    ctx = ctx or load_auth_context(db, user)
    return TokenResponse(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in_seconds=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
        roles=ctx.roles,
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(f"register:{client_ip(request)}", limit=settings.rate_limit_register_per_hour, window_seconds=3600)
    try:
        validate_password(payload.password)
    except ValueError as exc:
        raise ConflictError(str(exc), code="weak_password", status_code=422)

    existing = db.execute(
        select(User).where(or_(User.phone == payload.phone, User.email == payload.email if payload.email else False))
    ).scalars().first()
    if existing:
        raise ConflictError("An account with this phone or email already exists.", code="account_exists")

    user = User(
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        preferred_language=payload.preferred_language,
    )
    db.add(user)
    db.flush()

    customer_role = db.execute(select(Role).where(Role.code == "CUSTOMER")).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=customer_role.id, granted_by_id=user.id))
    profile = CustomerProfile(user_id=user.id)
    db.add(profile)
    db.flush()
    db.add(CustomerPreference(customer_id=profile.id))

    meta = request_meta(request)
    write_audit(db, actor=user, action="auth.register", entity_type="user", entity_id=user.id, ip=meta["ip"], user_agent=meta["user_agent"])
    response = _issue_tokens(db, user, request)
    db.flush()
    commit_or_raise(db)  # durable BEFORE the 201 is returned
    return response


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(f"login:ip:{ip}", limit=settings.rate_limit_login_per_minute * 3, window_seconds=300)
    check_rate_limit(f"login:id:{payload.identifier.lower()}", limit=settings.rate_limit_login_per_minute, window_seconds=300)

    identifier = payload.identifier.strip()
    phone = None
    try:
        phone = normalize_phone(identifier)
    except ValueError:
        pass

    stmt = select(User).where(User.email == identifier.lower()) if "@" in identifier else select(User).where(User.phone == phone)
    user = db.execute(stmt).scalars().first()

    if user is None:
        # Equalise work to blunt user enumeration; log the security event (no DB row:
        # there is no account to attribute it to).
        verify_password(payload.password, hash_password("dummy-password-1"))
        log.warning("SECURITY auth.login_failed reason=unknown_account ip=%s identifier_hash=%s",
                    ip, hash_refresh_token(identifier.lower())[:16])
        raise AuthError("Invalid credentials.", code="invalid_credentials")

    password_ok = verify_password(payload.password, user.password_hash)

    # ---- from here on the user row is locked: counter read/modify/write is serialised ----
    locked = _locked_user(db, user.id)
    now = _now()

    if not password_ok:
        if locked.locked_until and locked.locked_until > now:
            # Already locked by a concurrent attempt: refuse without incrementing.
            raise AuthError(
                "Account temporarily locked after repeated failed logins. Try again later.",
                code="account_locked",
                status_code=423,
            )
        locked.failed_login_count += 1
        just_locked = False
        if locked.failed_login_count >= LOCKOUT_THRESHOLD:
            locked.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            locked.failed_login_count = 0
            just_locked = True
            log.warning("SECURITY account_locked user_id=%s ip=%s minutes=%s", locked.id, ip, LOCKOUT_MINUTES)

        meta = request_meta(request)
        write_audit(
            db, actor=locked, action="auth.login_failed", entity_type="user", entity_id=locked.id,
            after={"locked": just_locked, "attempts": locked.failed_login_count}, ip=meta["ip"], user_agent=meta["user_agent"],
        )
        if just_locked:
            write_audit(
                db, actor=locked, action="auth.account_locked", entity_type="user", entity_id=locked.id,
                after={"locked_until": locked.locked_until.isoformat(), "minutes": LOCKOUT_MINUTES},
                ip=meta["ip"], user_agent=meta["user_agent"],
            )
        db.flush()
        _commit_security_state(db, AuthError("Invalid credentials.", code="invalid_credentials"))

    # Correct password — but a concurrent attacker may have locked the account meanwhile.
    if locked.locked_until and locked.locked_until > now:
        raise AuthError(
            "Account temporarily locked after repeated failed logins. Try again later.",
            code="account_locked",
            status_code=423,
        )
    if not locked.is_active:
        raise AuthError("Account is suspended. Contact support.", code="account_inactive", status_code=403)

    locked.failed_login_count = 0
    locked.locked_until = None
    locked.last_login_at = now
    meta = request_meta(request)
    write_audit(db, actor=locked, action="auth.login", entity_type="user", entity_id=locked.id, ip=meta["ip"], user_agent=meta["user_agent"])
    response = _issue_tokens(db, locked, request)
    db.flush()
    commit_or_raise(db)  # the issued refresh token must exist before the client sees 200
    return response


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)

    # Step 0 — UNLOCKED probe purely to discover which user owns the token. A plain SELECT
    # takes no lock, so it cannot participate in a lock cycle.
    probe = db.execute(
        select(AuthRefreshToken.id, AuthRefreshToken.user_id).where(AuthRefreshToken.token_hash == token_hash)
    ).first()
    if probe is None:
        raise AuthError("Invalid refresh token.", code="invalid_refresh_token")

    # Step 1 — canonical order: USER ROW FIRST.
    locked_user = _lock_user_row(db, probe.user_id)
    if locked_user is None:
        raise AuthError("Invalid refresh token.", code="invalid_refresh_token")

    # Step 2 — canonical order: TOKEN ROW SECOND, re-read under the lock. The row may have
    # been rotated or revoked by another transaction while this one waited for the user lock.
    row = _lock_token_row(db, probe.id)
    now = _now()
    if row is None:
        raise AuthError("Invalid refresh token.", code="invalid_refresh_token")

    if row.revoked_at is not None:
        # Reuse of a rotated token: revoke the whole family. The user row is already held,
        # so this only ever takes token locks after the user lock — same order as every
        # other path. Revocation is committed BEFORE raising so it cannot be rolled back.
        revoked = db.execute(
            update(AuthRefreshToken)
            .where(AuthRefreshToken.user_id == locked_user.id, AuthRefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        ).rowcount or 0
        log.warning(
            "SECURITY refresh_token_reuse user_id=%s revoked_sessions=%s ip=%s",
            locked_user.id, revoked, client_ip(request),
        )
        meta = request_meta(request)
        write_audit(
            db, actor=locked_user, action="auth.refresh_reuse_detected", entity_type="user",
            entity_id=locked_user.id, after={"revoked_sessions": revoked},
            ip=meta["ip"], user_agent=meta["user_agent"],
        )
        db.flush()
        _commit_security_state(db, AuthError("Refresh token already used. All sessions revoked.", code="refresh_token_reused"))

    if row.expires_at <= now:
        raise AuthError("Refresh token expired. Please log in again.", code="refresh_token_expired")

    if not locked_user.is_active:
        raise AuthError("Account is inactive.", code="account_inactive")

    response = _issue_tokens(db, locked_user, request)
    db.flush()
    new_row = db.execute(
        select(AuthRefreshToken).where(AuthRefreshToken.token_hash == hash_refresh_token(response.refresh_token))
    ).scalars().first()
    row.revoked_at = now
    row.replaced_by_id = new_row.id if new_row else None
    db.flush()
    commit_or_raise(db)  # rotation (revoke old + insert new) durable BEFORE returning
    return response


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the caller's password. Clears `must_change_password` and revokes all sessions.

    A fresh token pair is returned so the caller stays signed in on this device only.
    """
    locked = _locked_user(db, user.id)

    if not verify_password(payload.current_password, locked.password_hash):
        meta = request_meta(request)
        write_audit(
            db, actor=locked, action="auth.password_change_failed", entity_type="user", entity_id=locked.id,
            ip=meta["ip"], user_agent=meta["user_agent"],
        )
        db.flush()
        _commit_security_state(
            db, AuthError("Current password is incorrect.", code="invalid_credentials", status_code=401)
        )

    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise ValidationAppError(str(exc), code="weak_password")
    if payload.new_password == payload.current_password:
        raise ValidationAppError("New password must be different from the current password.", code="password_unchanged")

    now = _now()
    locked.password_hash = hash_password(payload.new_password)
    locked.must_change_password = False
    # Revoke every existing session, then issue a fresh pair for this device.
    db.execute(
        update(AuthRefreshToken)
        .where(AuthRefreshToken.user_id == locked.id, AuthRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    meta = request_meta(request)
    write_audit(
        db, actor=locked, action="auth.password_changed", entity_type="user", entity_id=locked.id,
        ip=meta["ip"], user_agent=meta["user_agent"],
    )
    response = _issue_tokens(db, locked, request)
    db.flush()
    # The session revocations and the new password hash must be durable before the caller
    # is told the change succeeded — otherwise a concurrently issued session survives.
    commit_or_raise(db)
    return response


@router.post("/logout", response_model=MessageResponse)
def logout(
    payload: LogoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Canonical lock order: USER row first, even though only token rows are mutated.
    locked_user = _lock_user_row(db, user.id)
    now = _now()
    if locked_user is None:
        raise AuthError("Account does not exist.", code="account_inactive")
    if payload.all_sessions:
        db.execute(
            update(AuthRefreshToken)
            .where(AuthRefreshToken.user_id == locked_user.id, AuthRefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    elif payload.refresh_token:
        row = db.execute(
            select(AuthRefreshToken).where(
                AuthRefreshToken.token_hash == hash_refresh_token(payload.refresh_token),
                AuthRefreshToken.user_id == locked_user.id,
            )
        ).scalars().first()
        if row:
            row.revoked_at = now
    write_audit(db, actor=user, action="auth.logout", entity_type="user", entity_id=user.id)
    db.flush()
    commit_or_raise(db)  # revocation durable before the caller is told it succeeded
    return MessageResponse(message="Logged out.")


@router.get("/me", response_model=MeResponse)
def me(ctx: AuthContext = Depends(get_auth_context)):
    return MeResponse(
        user=UserOut.model_validate(ctx.user),
        roles=ctx.roles,
        permissions=sorted(ctx.permissions),
    )


@router.post("/verify-otp", response_model=MessageResponse)
def verify_otp(payload: VerifyOtpRequest):
    if not (settings.otp_enabled and settings.sms_provider and settings.sms_api_key):
        raise ServiceUnavailableError(
            "OTP verification is not configured on this deployment. Set OTP_ENABLED, SMS_PROVIDER and SMS_API_KEY (an approved Indian SMS provider) to enable it.",
            code="otp_not_configured",
        )
    raise ServiceUnavailableError(
        "OTP provider integration is configured but no OTP delivery adapter is implemented for this provider yet.",
        code="otp_adapter_missing",
    )
