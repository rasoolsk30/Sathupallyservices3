"""Finance: payments, invoices, commissions, settlements, compensation, refunds, ledger."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.columns import enum_col
from app.models.enums import (
    CommissionStatus,
    EmployeeCompStatus,
    EmployeeCompType,
    InvoiceStatus,
    LedgerAccount,
    LedgerDirection,
    PaymentMethodType,
    PaymentStatus,
    RefundMethod,
    RefundStatus,
    SettlementStatus,
    WebhookStatus,
)


class PaymentMethod(Base, PKMixin, TimestampMixin):
    __tablename__ = "payment_methods"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)
    name_te: Mapped[str | None] = mapped_column(String(100))
    method_type: Mapped[str] = mapped_column(String(20), nullable=False)  # CASH / UPI / GATEWAY
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Payment(Base, PKMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="payment_amount_positive"),
        Index("ix_payments_booking", "booking_id", "status"),
        Index("ix_payments_gateway_order", "gateway_order_id"),
    )

    payment_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    payer_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    method_type: Mapped[PaymentMethodType] = mapped_column(enum_col(PaymentMethodType, "payment_method_type", 30), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        enum_col(PaymentStatus, "payment_status", 20), default=PaymentStatus.PENDING, nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    gateway_provider: Mapped[str | None] = mapped_column(String(30))
    gateway_order_id: Mapped[str | None] = mapped_column(String(120))
    gateway_payment_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    gateway_signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    collected_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    evidence_file_key: Mapped[str | None] = mapped_column(String(500))
    reference_note: Mapped[str | None] = mapped_column(String(300))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentWebhookEvent(Base, PKMixin):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),)

    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[WebhookStatus] = mapped_column(
        enum_col(WebhookStatus, "webhook_status", 15), default=WebhookStatus.RECEIVED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(500))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Invoice(Base, PKMixin, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (CheckConstraint("total_paise >= 0", name="invoice_total_non_negative"),)

    invoice_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customer_profiles.id", ondelete="RESTRICT"), nullable=False)
    subtotal_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        enum_col(InvoiceStatus, "invoice_status", 15), default=InvoiceStatus.ISSUED, nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base, PKMixin):
    __tablename__ = "invoice_items"

    invoice_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    line_total_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Commission(Base, PKMixin, TimestampMixin):
    __tablename__ = "commissions"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_commission_booking"),
        CheckConstraint("commission_paise >= 0", name="commission_non_negative"),
        CheckConstraint("rate_bps BETWEEN 0 AND 10000", name="commission_rate_range"),
        Index("ix_commissions_provider_status", "provider_id", "status"),
    )

    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT"), nullable=False)
    base_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[CommissionStatus] = mapped_column(
        enum_col(CommissionStatus, "commission_status", 15), default=CommissionStatus.ESTIMATED, nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderSettlement(Base, PKMixin, TimestampMixin):
    __tablename__ = "provider_settlements"
    __table_args__ = (
        CheckConstraint("net_payable_paise >= 0", name="settlement_net_non_negative"),
        Index("ix_settlements_provider_status", "provider_id", "status"),
    )

    settlement_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="RESTRICT"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    gross_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    commission_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    adjustments_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    net_payable_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[SettlementStatus] = mapped_column(
        enum_col(SettlementStatus, "settlement_status", 15), default=SettlementStatus.DRAFT, nullable=False
    )
    method: Mapped[str | None] = mapped_column(String(30))
    reference: Mapped[str | None] = mapped_column(String(120))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(String(500))

    items: Mapped[list["SettlementItem"]] = relationship(back_populates="settlement", cascade="all, delete-orphan")


class SettlementItem(Base, PKMixin):
    __tablename__ = "settlement_items"

    settlement_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_settlements.id", ondelete="CASCADE"), nullable=False)
    commission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("commissions.id", ondelete="RESTRICT"), nullable=False)
    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)

    settlement: Mapped[ProviderSettlement] = relationship(back_populates="items")


class EmployeeCompensation(Base, PKMixin, TimestampMixin):
    __tablename__ = "employee_compensation"
    __table_args__ = (
        CheckConstraint("amount_paise >= 0", name="employee_comp_non_negative"),
        Index("ix_employee_comp_employee_status", "employee_id", "status"),
        UniqueConstraint("employee_id", "booking_id", "comp_type", name="uq_employee_comp_booking_type"),
    )

    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employee_profiles.id", ondelete="RESTRICT"), nullable=False)
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"))
    comp_type: Mapped[EmployeeCompType] = mapped_column(enum_col(EmployeeCompType, "employee_comp_type", 20), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[EmployeeCompStatus] = mapped_column(
        enum_col(EmployeeCompStatus, "employee_comp_status", 15), default=EmployeeCompStatus.PENDING, nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))


class Refund(Base, PKMixin, TimestampMixin):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="refund_amount_positive"),
        Index("ix_refunds_payment", "payment_id", "status"),
    )

    refund_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False)
    booking_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[RefundMethod] = mapped_column(enum_col(RefundMethod, "refund_method", 15), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        enum_col(RefundStatus, "refund_status", 20), default=RefundStatus.REQUESTED, nullable=False
    )
    gateway_refund_id: Mapped[str | None] = mapped_column(String(120))
    processed_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(300))


class FinancialLedger(Base, PKMixin):
    __tablename__ = "financial_ledger"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ledger_amount_positive"),
        Index("ix_ledger_entry_date", "entry_date"),
        Index("ix_ledger_booking", "booking_id"),
        Index("ix_ledger_account", "account"),
    )

    entry_group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", ondelete="RESTRICT"))
    payment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("payments.id", ondelete="RESTRICT"))
    settlement_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("provider_settlements.id", ondelete="RESTRICT"))
    refund_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("refunds.id", ondelete="RESTRICT"))
    account: Mapped[LedgerAccount] = mapped_column(enum_col(LedgerAccount, "ledger_account", 40), nullable=False)
    direction: Mapped[LedgerDirection] = mapped_column(enum_col(LedgerDirection, "ledger_direction", 10), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
