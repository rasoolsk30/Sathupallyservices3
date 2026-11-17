"""Notifications, preferences and message templates."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin
from app.models.columns import enum_col
from app.models.enums import NotificationChannel, NotificationStatus


class Notification(Base, PKMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_code: Mapped[str] = mapped_column(String(60), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_col(NotificationChannel, "notification_channel", 20), default=NotificationChannel.IN_APP, nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        enum_col(NotificationStatus, "notification_status", 15), default=NotificationStatus.QUEUED, nullable=False
    )
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_te: Mapped[str | None] = mapped_column(String(250))
    body_en: Mapped[str] = mapped_column(Text, nullable=False)
    body_te: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationPreference(Base, PKMixin, TimestampMixin):
    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp_link: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MessageTemplate(Base, PKMixin, TimestampMixin):
    __tablename__ = "message_templates"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="IN_APP", nullable=False)
    subject_template: Mapped[str | None] = mapped_column(String(200))
    body_en: Mapped[str] = mapped_column(Text, nullable=False)
    body_te: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
