"""Audit logging service — writes action records to the audit_logs table."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    action: str,
    request: Request | None = None,
    user_id: UUID | None = None,
    details: dict | None = None,
) -> None:
    """Write a single audit log entry."""
    ip = None
    if request and request.client:
        ip = request.client.host

    entry = AuditLog(
        user_id=user_id,
        action=action,
        ip_address=ip,
        details=details,
    )
    db.add(entry)
    # Don't flush here — let the caller's transaction handle it
