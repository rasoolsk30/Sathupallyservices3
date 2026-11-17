"""Booking engine tables: bookings, assignments, status history, quotations, evidence, time logs."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.columns import enum_col
from app.models.enums import (
    AssignmentStatus,
    AssignmentType,
    BookingStatus,
    BookingType,
    EvidenceType,
    ProviderModel,
    QuotationStatus,
    TimeLogEvent,
)


class Booking(Base, PKMixin, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_status_created", "status", "created_at"),
        Index("ix_bookings_customer", "customer_id", "created_at"),
        Index("ix_bookings_provider", "assigned_provider_id", "status"),
        Index("ix_bookings_employee", "assigned_employee_id", "status"),
        CheckConstraint("approved_amount_paise >= 0", name="approved_amount_non_negative"),
        CheckConstraint("final_amount_paise >= 0", name="final_amount_non_negative"),
    )

    booking_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customer_profiles.id", ondelete="RESTRICT"), nullable=False)
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id", ondelete="RESTRICT"), nullable=False)
    address_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customer_addresses.id", ondelete="RESTRICT"), nullable=False)

    booking_type: Mapped[BookingType] = mapped_column(enum_col(BookingType, "booking_type", 20), nullable=False)
    provider_model: Mapped[ProviderModel] = mapped_column(
        enum_col(ProviderModel, "booking_provider_model", 25), default=ProviderModel.INDEPENDENT, nullable=False
    )
    status: Mapped[BookingStatus] = mapped_column(
        enum_col(BookingStatus, "booking_status", 30), default=BookingStatus.REQUESTED, nullable=False, index=True
    )

    problem_description: Mapped[str] = mapped_column(Text, nullable=False)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preferred_date: Mapped[date | None] = mapped_column(Date)
    preferred_slot: Mapped[str | None] = mapped_column(String(20))  # MORNING / AFTERNOON / EVENING / FLEXIBLE

    assigned_provider_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT")
    )
    assigned_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employee_profiles.id", ondelete="RESTRICT")
    )

    quoted_total_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    approved_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    final_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    cancellation_fee_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    customer_confirmed_completion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)

    status_history: Mapped[list["BookingStatusHistory"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingStatusHistory.id"
    )
    quotations: Mapped[list["Quotation"]] = relationship(back_populates="booking", cascade="all, delete-orphan")
    items: Mapped[list["BookingItem"]] = relationship(back_populates="booking", cascade="all, delete-orphan")


class BookingItem(Base, PKMixin):
    __tablename__ = "booking_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="booking_item_qty_positive"),)

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="items")


class BookingAssignment(Base, PKMixin, TimestampMixin):
    __tablename__ = "booking_assignments"
    __table_args__ = (
        Index(
            "uq_active_assignment_per_booking",
            "booking_id",
            unique=True,
            postgresql_where=text("status IN ('OFFERED','ACCEPTED')"),
        ),
        Index("ix_booking_assignments_provider", "provider_id", "status"),
        Index("ix_booking_assignments_employee", "employee_id", "status"),
        CheckConstraint(
            "(provider_id IS NOT NULL AND employee_id IS NULL) OR (provider_id IS NULL AND employee_id IS NOT NULL)",
            name="assignment_exactly_one_assignee",
        ),
    )

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT"))
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    assigned_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    assignment_type: Mapped[AssignmentType] = mapped_column(enum_col(AssignmentType, "assignment_type", 15), nullable=False)
    status: Mapped[AssignmentStatus] = mapped_column(
        enum_col(AssignmentStatus, "assignment_status", 15), default=AssignmentStatus.OFFERED, nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(300))


class BookingStatusHistory(Base, PKMixin):
    __tablename__ = "booking_status_history"
    __table_args__ = (Index("ix_booking_status_history_booking", "booking_id", "id"),)

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(500))
    extra: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="status_history")


class Quotation(Base, PKMixin, TimestampMixin):
    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("booking_id", "provider_id", "version", name="uq_quotation_version"),
        CheckConstraint("labour_paise >= 0 AND inspection_paise >= 0 AND material_estimate_paise >= 0", name="quote_amounts_non_negative"),
        CheckConstraint("travel_paise >= 0 AND tax_paise >= 0 AND total_paise >= 0", name="quote_amounts2_non_negative"),
        Index("ix_quotations_booking", "booking_id", "status"),
    )

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[QuotationStatus] = mapped_column(
        enum_col(QuotationStatus, "quotation_status", 15), default=QuotationStatus.SUBMITTED, nullable=False
    )

    labour_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    inspection_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    material_estimate_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    travel_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warranty_terms: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    is_additional_work: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="quotations")
    items: Mapped[list["QuotationItem"]] = relationship(back_populates="quotation", cascade="all, delete-orphan")


class QuotationItem(Base, PKMixin):
    __tablename__ = "quotation_items"
    __table_args__ = (CheckConstraint("amount_paise >= 0", name="quotation_item_amount_non_negative"),)

    quotation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    quotation: Mapped[Quotation] = relationship(back_populates="items")


class JobEvidence(Base, PKMixin):
    __tablename__ = "job_evidence"
    __table_args__ = (Index("ix_job_evidence_booking", "booking_id", "evidence_type"),)

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    uploaded_by_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(enum_col(EvidenceType, "evidence_type", 15), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JobTimeLog(Base, PKMixin):
    __tablename__ = "job_time_logs"

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="SET NULL"))
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="SET NULL"))
    event: Mapped[TimeLogEvent] = mapped_column(enum_col(TimeLogEvent, "time_log_event", 10), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
