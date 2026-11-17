"""Reviews, complaints/disputes and support tickets."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.columns import enum_col
from app.models.enums import ComplaintStatus, ReviewStatus, TicketChannel, TicketStatus


class Review(Base, PKMixin, TimestampMixin):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        Index("ix_reviews_provider_status", "provider_id", "status"),
    )

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customer_profiles.id", ondelete="RESTRICT"), nullable=False)
    provider_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT"))
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(
        enum_col(ReviewStatus, "review_status", 15), default=ReviewStatus.PUBLISHED, nullable=False
    )
    admin_note: Mapped[str | None] = mapped_column(String(500))


class Complaint(Base, PKMixin, TimestampMixin):
    __tablename__ = "complaints"
    __table_args__ = (Index("ix_complaints_status_created", "status", "created_at"),)

    complaint_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"))
    raised_by_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    against_provider_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT"))
    against_employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ComplaintStatus] = mapped_column(
        enum_col(ComplaintStatus, "complaint_status", 15), default=ComplaintStatus.OPEN, nullable=False
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["DisputeMessage"]] = relationship(back_populates="complaint", cascade="all, delete-orphan")


class DisputeMessage(Base, PKMixin):
    __tablename__ = "dispute_messages"

    complaint_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False)
    author_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    complaint: Mapped[Complaint] = relationship(back_populates="messages")


class SupportTicket(Base, PKMixin, TimestampMixin):
    __tablename__ = "support_tickets"
    __table_args__ = (Index("ix_support_tickets_status", "status", "created_at"),)

    ticket_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    requester_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[TicketChannel] = mapped_column(
        enum_col(TicketChannel, "ticket_channel", 15), default=TicketChannel.IN_APP, nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        enum_col(TicketStatus, "ticket_status", 15), default=TicketStatus.OPEN, nullable=False
    )
    assigned_to_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    resolution: Mapped[str | None] = mapped_column(Text)
