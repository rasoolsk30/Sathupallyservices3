"""Shared schema helpers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class MessageResponse(BaseModel):
    message: str


def paise_to_rupees(paise: int) -> str:
    """Format integer paise as ₹ string with 2 decimals (display only — never compute with floats)."""
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    return f"{sign}₹{paise // 100}.{paise % 100:02d}"


def to_ist(dt: datetime | None) -> datetime | None:
    """Storage is UTC; the API returns UTC ISO strings. Frontend renders IST."""
    return dt
