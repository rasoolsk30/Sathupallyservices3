"""Catalog: villages, zones, categories, services, pricing, provider skills/areas/availability."""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
from app.models.enums import PriceType, Proficiency


class Village(Base, PKMixin, TimestampMixin):
    __tablename__ = "villages"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name_te: Mapped[str | None] = mapped_column(String(100))
    mandal: Mapped[str] = mapped_column(String(100), default="Sathupally", nullable=False)
    district: Mapped[str] = mapped_column(String(100), default="Khammam", nullable=False)
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))

    zones: Mapped[list["ServiceZone"]] = relationship(back_populates="village")


class ServiceZone(Base, PKMixin, TimestampMixin):
    __tablename__ = "service_zones"
    __table_args__ = (UniqueConstraint("name", "village_id", name="uq_service_zones_name_village"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    village: Mapped[Village] = relationship(back_populates="zones")


class ServiceCategory(Base, PKMixin, TimestampMixin):
    __tablename__ = "service_categories"

    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    name_te: Mapped[str] = mapped_column(String(120), nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_te: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(60))
    image_url: Mapped[str | None] = mapped_column(String(500))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    services: Mapped[list["Service"]] = relationship(back_populates="category")


class Service(Base, PKMixin, TimestampMixin):
    __tablename__ = "services"

    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_categories.id", ondelete="RESTRICT"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_te: Mapped[str] = mapped_column(String(150), nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_te: Mapped[str | None] = mapped_column(Text)
    required_skills: Mapped[list | None] = mapped_column(JSONB, default=list)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    safety_instructions_en: Mapped[str | None] = mapped_column(Text)
    safety_instructions_te: Mapped[str | None] = mapped_column(Text)
    coverage_note: Mapped[str | None] = mapped_column(String(300))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))

    category: Mapped[ServiceCategory] = relationship(back_populates="services")
    pricing: Mapped[list["ServicePricing"]] = relationship(back_populates="service", cascade="all, delete-orphan")


class ServicePricing(Base, PKMixin, TimestampMixin):
    __tablename__ = "service_pricing"
    __table_args__ = (
        CheckConstraint("base_price_paise >= 0", name="base_price_non_negative"),
        CheckConstraint("tax_rate_bps BETWEEN 0 AND 10000", name="tax_rate_range"),
        Index("ix_service_pricing_service_active", "service_id", "is_active"),
    )

    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    price_type: Mapped[PriceType] = mapped_column(enum_col(PriceType, "price_type", 20), nullable=False)
    base_price_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    inspection_fee_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_rate_bps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))

    service: Mapped[Service] = relationship(back_populates="pricing")


class ProviderSkill(Base, PKMixin, TimestampMixin):
    __tablename__ = "provider_skills"
    __table_args__ = (UniqueConstraint("provider_id", "service_id", name="uq_provider_skills_pair"),)

    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    proficiency: Mapped[Proficiency] = mapped_column(
        enum_col(Proficiency, "proficiency", 15), default=Proficiency.INTERMEDIATE, nullable=False
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProviderServiceArea(Base, PKMixin, TimestampMixin):
    __tablename__ = "provider_service_areas"
    __table_args__ = (
        UniqueConstraint("provider_id", "village_id", "zone_id", name="uq_provider_area"),
        Index("ix_provider_areas_village", "village_id"),
    )

    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False)
    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id", ondelete="CASCADE"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("service_zones.id", ondelete="SET NULL"))


class ProviderAvailability(Base, PKMixin):
    __tablename__ = "provider_availability"
    __table_args__ = (
        UniqueConstraint("provider_id", "day_of_week", "start_time", name="uq_provider_availability_slot"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="day_of_week_range"),
        CheckConstraint("end_time > start_time", name="time_order"),
    )

    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Monday
    start_time: Mapped[time] = mapped_column(nullable=False)
    end_time: Mapped[time] = mapped_column(nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
