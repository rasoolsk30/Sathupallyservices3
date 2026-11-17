"""Column helpers."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum


def enum_col(enum_cls, name: str, length: int = 40):
    """Portable string-backed enum with a CHECK constraint (no native PG enum types)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )
