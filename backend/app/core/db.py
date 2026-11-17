"""Database engine/session wiring (synchronous SQLAlchemy 2.x with psycopg3)."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def commit_or_raise(db: Session) -> None:
    """Commit the unit of work BEFORE the endpoint returns its success response.

    Why this exists
    ---------------
    `get_db` is a FastAPI `yield` dependency, and its exit code runs *after* the
    response has been handed to the ASGI server. The server flushes that response to
    the client immediately, so a commit performed in the dependency teardown races the
    client. Measured on this stack: 20/20 responses reached the client while the
    transaction was still uncommitted (~3 ms later). A caller could therefore observe
    "200 OK" and then read stale state from a *different* connection.

    Security consequence: `/auth/change-password` revokes every session, but a login
    that committed only after the response is sent escapes that revocation, because the
    revocation UPDATE could not see the still-uncommitted row.

    Rule for this codebase: every mutating endpoint commits explicitly, on the request's
    own session, before returning. The dependency teardown remains only as a safety net
    and is never relied upon for durability.
    """
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_db() -> Generator[Session, None, None]:
    """Request-scoped session.

    SAFETY NET ONLY: the commit below happens after the response is sent, so it cannot
    guarantee read-after-write visibility. Mutating endpoints MUST call
    `commit_or_raise(db)` before returning — see that function's docstring.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
