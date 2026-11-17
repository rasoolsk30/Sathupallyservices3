"""Customer-owned data: addresses and preferences."""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class CustomerAddress(Base, PKMixin, TimestampMixin):
    __tablename__ = "customer_addresses"
    __table_args__ = (
        Index("ix_customer_addresses_customer", "customer_id", "is_active"),
        UniqueConstraint("customer_id", "label", name="uq_customer_address_label"),
    )

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer_profiles.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)  # Home / Work / Other
    line1: Mapped[str] = mapped_column(String(200), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(200))
    landmark: Mapped[str | None] = mapped_column(String(150))
    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id", ondelete="RESTRICT"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("service_zones.id", ondelete="SET NULL"))
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CustomerPreference(Base, PKMixin, TimestampMixin):
    __tablename__ = "customer_preferences"

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer_profiles.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    in_app_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)
