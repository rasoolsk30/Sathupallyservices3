"""Application settings loaded from environment (.env supported)."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
log = logging.getLogger("ssh.config")

# Production safety — credential denylists.
# Matching is case-insensitive on BOTH sides so that "CHANGE_ME", "change_me" and
# "Change_Me" are all rejected, as are mixed-case development passwords.
_DEV_PASSWORD_EXACT = {
    "password", "password1", "passw0rd", "postgres", "admin", "root", "secret", "123456",
    "12345678", "changeme", "change_me", "change-me", "dev_local_only_change_me",
    "dev_local_only", "insecure", "example", "test", "dev", "local", "localdev", "qwerty",
}
_DEV_PASSWORD_SUBSTRINGS = (
    "change_me", "change-me", "changeme", "dev_local_only", "dev-only", "devonly",
    "insecure", "example", "password", "passw0rd", "letmein", "localdev",
)
_DEV_JWT_SUBSTRINGS = (
    "change", "changeme", "dev-only", "devonly", "insecure", "example", "secret-key", "jwt-secret",
)
MIN_DB_PASSWORD_LENGTH = 12
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    app_name: str = "SATHUPALLY SERVICE HUB"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://ssh_app:dev_local_only_change_me@127.0.0.1:5432/sathupally"
    test_database_url: str = "postgresql+psycopg://ssh_app:dev_local_only_change_me@127.0.0.1:5432/sathupally_test"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    password_min_length: int = 8

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Comma-separated IPs/CIDRs of reverse proxies that are ALLOWED to set X-Forwarded-For.
    # Empty (default) => X-Forwarded-For is ignored entirely and the socket peer address is used.
    trusted_proxies: str = ""

    storage_dir: str = str(BASE_DIR.parent / "storage")
    max_upload_mb: int = 8

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    sms_provider: str = ""
    sms_api_key: str = ""
    otp_enabled: bool = False
    whatsapp_support_number: str = ""

    payment_gateway: str = ""
    payment_gateway_key_id: str = ""
    payment_gateway_key_secret: str = ""
    payment_gateway_webhook_secret: str = ""

    default_commission_bps: int = 1000
    booking_timezone: str = "Asia/Kolkata"
    currency: str = "INR"

    admin_mfa_required: bool = False
    rate_limit_login_per_minute: int = 10
    rate_limit_register_per_hour: int = 5

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return p

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def gateway_enabled(self) -> bool:
        return bool(self.payment_gateway and self.payment_gateway_key_id and self.payment_gateway_key_secret)

    # ------------------------------------------------------------------
    # Production safety
    # ------------------------------------------------------------------
    def production_problems(self) -> list[str]:
        """Return every production-safety violation. Empty list == safe to boot."""
        if not self.is_production:
            return []

        problems: list[str] = []

        secret = self.jwt_secret or ""
        lowered_secret = secret.lower()
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            problems.append(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters.")
        if any(marker in lowered_secret for marker in _DEV_JWT_SUBSTRINGS):
            problems.append("JWT_SECRET still contains a development/default marker.")

        try:
            url = make_url(self.database_url)
        except Exception:
            problems.append("DATABASE_URL is not a parseable database URL.")
            return problems

        if not url.database:
            problems.append("DATABASE_URL does not name a database.")

        password = url.password or ""
        if not password:
            problems.append("DATABASE_URL has no password (passwords are mandatory in production).")
        else:
            lowered_password = password.lower()
            if (
                lowered_password in _DEV_PASSWORD_EXACT
                or any(marker in lowered_password for marker in _DEV_PASSWORD_SUBSTRINGS)
                or len(password) < MIN_DB_PASSWORD_LENGTH
            ):
                problems.append(
                    "DATABASE_URL uses a default/development password "
                    "(rejected case-insensitively; production passwords must be "
                    f"at least {MIN_DB_PASSWORD_LENGTH} characters and must not contain "
                    "change_me/dev_local_only/password/example/insecure markers)."
                )
        return problems

    def assert_production_safe(self) -> None:
        """Refuse to boot production with development defaults or weak credentials."""
        problems = self.production_problems()
        if problems:
            raise RuntimeError("PRODUCTION SAFETY CHECK FAILED: " + " | ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
