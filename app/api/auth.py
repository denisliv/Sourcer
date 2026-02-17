"""Authentication routes: login, logout, current user info."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import IS_PRODUCTION
from app.core.database import get_db
from app.core.security import generate_session_token, session_expires_at, verify_password
from app.models.session import Session
from app.models.user import User
from app.services.audit import log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    ok: bool = True
    must_change_password: bool = False
    redirect: str = "/"


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # Find user
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    # Create session
    token = generate_session_token()
    expires = session_expires_at()
    sess = Session(
        user_id=user.id,
        token=token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        expires_at=expires,
    )
    db.add(sess)
    await db.flush()

    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days
        path="/",
    )

    # Audit log
    await log_action(db, "login", request=request, user_id=user.id)

    redirect = "/account" if user.must_change_password else "/"
    return LoginResponse(must_change_password=user.must_change_password, redirect=redirect)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # Read cookie manually since we don't want dependency to redirect
    token = request.cookies.get("session_token")
    user_id = None
    if token:
        result = await db.execute(select(Session).where(Session.token == token))
        sess = result.scalar_one_or_none()
        if sess:
            user_id = sess.user_id
            await db.delete(sess)
            await db.flush()

    if user_id:
        await log_action(db, "logout", request=request, user_id=user_id)

    response.delete_cookie("session_token", path="/")
    return {"ok": True}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Return the current authenticated user's info (used by SPA pages)."""
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "must_change_password": user.must_change_password,
    }
