"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.assert_production_safe()
    if settings.is_production:
        logging.getLogger("ssh.security").warning(
            "RATE LIMITING IS IN-PROCESS: run exactly ONE uvicorn worker (or add a shared "
            "Redis-backed limiter) — multiple workers each keep their own counters, which "
            "multiplies the effective login/registration limits. See docs/KNOWN-LIMITATIONS.md."
        )
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    (settings.storage_path / "private").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,  # bearer tokens only; no ambient cookies => no CSRF surface
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Requested-With"],
)

install_error_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


_proxy_warning_at = 0.0


@app.middleware("http")
async def _forwarded_header_guard(request, call_next):
    """Warn when an X-Forwarded-For header arrives while no trusted proxy is configured.

    The application never trusts this header unless TRUSTED_PROXIES is set, but it is
    worth surfacing: it means either a misconfigured reverse proxy or a spoofing client.
    Note: run uvicorn with --no-proxy-headers (see docs/ARCHITECTURE.md §6) so the ASGI
    server does not rewrite request.client from the header before this check runs.
    """
    global _proxy_warning_at
    if not settings.trusted_proxies and request.headers.get("x-forwarded-for"):
        now = time.monotonic()
        if now - _proxy_warning_at > 60:
            _proxy_warning_at = now
            logging.getLogger("ssh.security").warning(
                "SECURITY X-Forwarded-For received but TRUSTED_PROXIES is empty; header ignored "
                "(peer=%s). If a reverse proxy is in front of this app, configure TRUSTED_PROXIES.",
                request.client.host if request.client else "unknown",
            )
    return await call_next(request)



@app.get("/healthz", tags=["health"])
def healthz():
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.app_name,
        "database": "ok" if db_ok else "unavailable",
        "env": settings.env,
    }
