"""Identity: users, roles, permissions, profiles, documents, attendance, auth sessions."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.columns import enum_col
from app.models.enums import (
    AttendanceStatus,
    CompensationType,
    DocumentStatus,
    DocumentType,
    EmploymentType,
    Language,
    ProviderType,
    VerificationStatus,
)


class User(Base, PKMixin, TimestampMixin):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_language: Mapped[Language] = mapped_column(enum_col(Language, "user_language", 5), default=Language.TE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_secret: Mapped[str | None] = mapped_column(String(255))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="UserRole.user_id"
    )
    customer_profile: Mapped["CustomerProfile | None"] = relationship(back_populates="user", uselist=False)
    provider_profile: Mapped["ProviderProfile | None"] = relationship(back_populates="user", uselist=False)
    employee_profile: Mapped["EmployeeProfile | None"] = relationship(back_populates="user", uselist=False)


class Role(Base, PKMixin, TimestampMixin):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role_permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="role")


class Permission(Base, PKMixin, TimestampMixin):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    role_permissions: Mapped[list["RolePermission"]] = relationship(back_populates="permission", cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),)

    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    role: Mapped[Role] = relationship(back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_permissions")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_pair"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)
    granted_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="user_roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(back_populates="user_roles")


class AuthRefreshToken(Base, PKMixin):
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (Index("ix_auth_refresh_tokens_user_active", "user_id", "revoked_at"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustomerProfile(Base, PKMixin, TimestampMixin):
    __tablename__ = "customer_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="customer_profile")


class ProviderProfile(Base, PKMixin, TimestampMixin):
    __tablename__ = "provider_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(
        enum_col(ProviderType, "provider_type", 30), default=ProviderType.INDEPENDENT, nullable=False
    )
    business_name: Mapped[str | None] = mapped_column(String(150))
    experience_years: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_col(VerificationStatus, "provider_verification_status", 20), default=VerificationStatus.PENDING, nullable=False
    )
    commission_rate_bps: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 2), default=0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suspended_reason: Mapped[str | None] = mapped_column(String(500))
    languages: Mapped[list | None] = mapped_column(JSONB, default=list)

    user: Mapped[User] = relationship(back_populates="provider_profile")
    documents: Mapped[list["ProviderDocument"]] = relationship(back_populates="provider", cascade="all, delete-orphan")


class EmployeeProfile(Base, PKMixin, TimestampMixin):
    __tablename__ = "employee_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    employee_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    designation: Mapped[str | None] = mapped_column(String(100))
    employment_type: Mapped[EmploymentType] = mapped_column(
        enum_col(EmploymentType, "employment_type", 20), default=EmploymentType.FULL_TIME, nullable=False
    )
    compensation_type: Mapped[CompensationType] = mapped_column(
        enum_col(CompensationType, "compensation_type", 30), default=CompensationType.PER_JOB, nullable=False
    )
    fixed_monthly_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    per_job_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    incentive_rate_bps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reports_to_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship(back_populates="employee_profile")


class ProviderDocument(Base, PKMixin, TimestampMixin):
    __tablename__ = "provider_documents"
    __table_args__ = (Index("ix_provider_documents_provider_status", "provider_id", "status"),)

    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(enum_col(DocumentType, "document_type", 25), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        enum_col(DocumentStatus, "document_status", 15), default=DocumentStatus.PENDING, nullable=False
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))

    provider: Mapped[ProviderProfile] = relationship(back_populates="documents")


class EmployeeAttendance(Base, PKMixin, TimestampMixin):
    __tablename__ = "employee_attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_employee_attendance_day"),
        Index("ix_employee_attendance_date", "work_date"),
    )

    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="CASCADE"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[AttendanceStatus] = mapped_column(
        enum_col(AttendanceStatus, "attendance_status", 15), default=AttendanceStatus.PRESENT, nullable=False
    )
    marked_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(String(500))
