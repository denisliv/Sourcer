"""FastAPI dependencies for authentication and authorization."""

from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import Session
from app.models.user import User


async def get_current_user(
    request: Request,
    session_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the session cookie, return the authenticated user."""
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    result = await db.execute(
        select(Session).where(
            Session.token == session_token,
            Session.expires_at > datetime.now(timezone.utc),
        )
    )
    sess = result.scalar_one_or_none()

    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    user_result = await db.execute(select(User).where(User.id == sess.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Ensure the current user is an admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
