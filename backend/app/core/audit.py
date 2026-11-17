"""Audit logging helper — append-only by convention and by API design (no delete endpoints)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.admin import AuditLog
from app.models.identity import User


def write_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before_data=before,
        after_data=after,
        ip_address=ip,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(entry)
    return entry
