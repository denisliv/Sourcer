"""FastAPI dependencies for authentication and authorization."""

from datetime import datetime, timezone
from uuid import UUID

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
        # For HTML pages, redirect to login; for API calls, return 401
        if _is_api_request(request):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        from fastapi.responses import RedirectResponse
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )

    result = await db.execute(
        select(Session).where(
            Session.token == session_token,
            Session.expires_at > datetime.now(timezone.utc),
        )
    )
    sess = result.scalar_one_or_none()

    if sess is None:
        if _is_api_request(request):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )

    # Load user
    user_result = await db.execute(select(User).where(User.id == sess.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Ensure the current user is an admin."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def _is_api_request(request: Request) -> bool:
    """Heuristic: API requests accept JSON or start with /api/."""
    accept = request.headers.get("accept", "")
    return request.url.path.startswith("/api/") or "application/json" in accept
