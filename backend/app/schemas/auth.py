"""Pydantic schemas for authentication and the current-user payload."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import Language

PHONE_RE = r"^\+91[6-9]\d{9}$"


def normalize_phone(raw: str) -> str:
    """Accept 10-digit Indian mobile, 0-prefixed, or +91 and return E.164 (+91XXXXXXXXXX)."""
    digits = "".join(ch for ch in raw.strip() if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("Enter a valid 10-digit Indian mobile number.")
    return f"+91{digits}"


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=128)
    preferred_language: Language = Language.TE

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Name is too short.")
        return v


class LoginRequest(BaseModel):
    identifier: str = Field(description="Phone number or email address", min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    all_sessions: bool = False


class VerifyOtpRequest(BaseModel):
    identifier: str
    otp_code: str = Field(min_length=4, max_length=8)


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone: str
    email: EmailStr | None
    full_name: str
    preferred_language: Language
    is_active: bool
    is_phone_verified: bool
    must_change_password: bool = False
    created_at: datetime


class ChangePasswordRequest(BaseModel):
    # Length/complexity are enforced by the shared password policy so the API returns a
    # consistent `weak_password` code instead of a generic schema-validation error.
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class MeResponse(BaseModel):
    user: UserOut
    roles: list[str]
    permissions: list[str]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: UserOut
    roles: list[str]
