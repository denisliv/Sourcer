"""Account routes: profile, change password, credentials management, logs."""

import base64
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import HH_CLIENT_ID, HH_REDIRECT_URI, HH_USER_AGENT, IS_PRODUCTION, SECRET_KEY
from app.core.database import get_db
from app.core.security import (
    decrypt_credentials,
    encrypt_credentials,
    hash_password,
    verify_password,
)
from app.models.audit_log import AuditLog
from app.models.credential import Credential
from app.models.user import User
from app.api.dependencies import get_current_user
from app.services.audit import log_action
from app.services.hh_oauth import (
    compute_expires_at,
    exchange_code_for_tokens,
    is_token_expired,
)

router = APIRouter(tags=["account"])


# --------------- Account status (JSON API for SPA) ---------------

@router.get("/api/account/status")
async def account_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return credential statuses as JSON (for SPA frontend)."""
    # HH credential
    result = await db.execute(
        select(Credential).where(Credential.user_id == user.id, Credential.provider == "hh")
    )
    hh_cred = result.scalar_one_or_none()
    hh_status = "not_configured"
    hh_expires_at = ""
    if hh_cred:
        hh_status = hh_cred.status
        try:
            data = decrypt_credentials(hh_cred.encrypted_data)
            iso = data.get("expires_at", "")
            if iso:
                try:
                    dt = datetime.fromisoformat(iso)
                    hh_expires_at = dt.strftime("%d.%m.%Y %H:%M UTC")
                except (ValueError, TypeError):
                    pass
                if is_token_expired(iso, buffer_seconds=0):
                    hh_status = "expired"
        except Exception:
            hh_status = "error"

    # LinkedIn credential
    result = await db.execute(
        select(Credential).where(Credential.user_id == user.id, Credential.provider == "linkedin")
    )
    li_cred = result.scalar_one_or_none()
    li_status = "not_configured"
    li_username = ""
    if li_cred:
        li_status = li_cred.status
        try:
            data = decrypt_credentials(li_cred.encrypted_data)
            li_username = data.get("username", "")
        except Exception:
            li_status = "error"

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name or "—",
            "is_admin": user.is_admin,
            "must_change_password": user.must_change_password,
        },
        "hh_status": hh_status,
        "hh_expires_at": hh_expires_at,
        "li_status": li_status,
        "li_username": li_username,
        "is_production": IS_PRODUCTION,
    }


# --------------- Change password ---------------

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/account/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Текущий пароль неверен",
        )
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен быть не менее 6 символов",
        )

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.add(user)
    await log_action(db, "password_change", request=request, user_id=user.id)
    await db.flush()
    return {"ok": True, "message": "Пароль успешно изменён"}


# --------------- HH OAuth flow ---------------

HH_OAUTH_AUTHORIZE_URL = "https://hh.ru/oauth/authorize"


def _generate_oauth_state(user_id: str) -> str:
    """Generate a signed state parameter for OAuth CSRF protection."""
    timestamp = str(int(time.time()))
    message = f"{user_id}:{timestamp}"
    sig = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(f"{message}:{sig}".encode()).decode()


def _verify_and_extract_user_id(state: str) -> str | None:
    """Verify state HMAC signature and return the user_id, or ``None`` if invalid."""
    try:
        decoded = base64.urlsafe_b64decode(state).decode()
        parts = decoded.rsplit(":", 2)
        if len(parts) != 3:
            return None
        uid, timestamp, sig = parts
        # State valid for 15 minutes
        if abs(int(time.time()) - int(timestamp)) > 900:
            return None
        message = f"{uid}:{timestamp}"
        expected = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return uid
    except Exception:
        return None


@router.get("/api/account/hh/authorize")
async def hh_authorize(user: User = Depends(get_current_user)):
    """Redirect the user to the HH OAuth authorization page."""
    state = _generate_oauth_state(str(user.id))
    params = urlencode({
        "response_type": "code",
        "client_id": HH_CLIENT_ID,
        "state": state,
        "redirect_uri": HH_REDIRECT_URI,
    })
    return RedirectResponse(f"{HH_OAUTH_AUTHORIZE_URL}?{params}")


@router.get("/api/account/hh/callback")
async def hh_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from HH.

    This endpoint does NOT require session auth — it validates the user via
    the signed *state* parameter.  This avoids problems when browsers strip
    cookies on cross-origin redirects.
    """
    # HH returned an error (user denied access, etc.)
    if error:
        msg = error_description or error
        return RedirectResponse(f"/account?hh_error={quote(msg)}", status_code=302)

    if not code or not state:
        return RedirectResponse("/account?hh_error=Отсутствует+code+или+state", status_code=302)

    # Verify state & extract user_id
    user_id_str = _verify_and_extract_user_id(state)
    if not user_id_str:
        return RedirectResponse("/account?hh_error=Недействительный+параметр+state", status_code=302)

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return RedirectResponse("/account?hh_error=Недействительный+user_id", status_code=302)

    # Exchange code for tokens
    try:
        tokens = await exchange_code_for_tokens(code)
    except Exception as exc:
        msg = quote(f"Ошибка обмена кода: {exc}")
        return RedirectResponse(f"/account?hh_error={msg}", status_code=302)

    # Build credential payload
    cred_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": compute_expires_at(tokens.get("expires_in", 3600)),
        "user_agent": HH_USER_AGENT,
    }
    encrypted = encrypt_credentials(cred_data)

    # Upsert credential
    result = await db.execute(
        select(Credential).where(Credential.user_id == user_id, Credential.provider == "hh")
    )
    cred = result.scalar_one_or_none()
    if cred:
        cred.encrypted_data = encrypted
        cred.status = "active"
    else:
        cred = Credential(
            user_id=user_id,
            provider="hh",
            status="active",
            encrypted_data=encrypted,
        )
        db.add(cred)

    await log_action(
        db, "credential_update", request=request, user_id=user_id,
        details={"provider": "hh", "method": "oauth"},
    )
    await db.flush()

    return RedirectResponse("/account?hh_connected=1", status_code=302)


# --------------- HH Dev OAuth helpers (local development only) ---------------


class DevCodeRequest(BaseModel):
    code: str


@router.get("/api/account/hh/authorize-url")
async def hh_authorize_url(user: User = Depends(get_current_user)):
    """Return the HH OAuth authorize URL as JSON (for dev UI to open in new tab)."""
    if IS_PRODUCTION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    state = _generate_oauth_state(str(user.id))
    params = urlencode({
        "response_type": "code",
        "client_id": HH_CLIENT_ID,
        "state": state,
        "redirect_uri": HH_REDIRECT_URI,
    })
    return {"url": f"{HH_OAUTH_AUTHORIZE_URL}?{params}"}


@router.post("/api/account/hh/dev-code")
async def hh_dev_code(
    body: DevCodeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange an authorization code for tokens (dev-only manual flow).

    Use when HH cannot redirect to localhost.  The developer copies the
    ``code`` parameter from the browser address bar after authorizing on HH
    and pastes it into the dev form.
    """
    if IS_PRODUCTION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    code = body.code.strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код авторизации не может быть пустым",
        )

    try:
        tokens = await exchange_code_for_tokens(code)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка обмена кода: {exc}",
        )

    cred_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": compute_expires_at(tokens.get("expires_in", 3600)),
        "user_agent": HH_USER_AGENT,
    }
    encrypted = encrypt_credentials(cred_data)

    result = await db.execute(
        select(Credential).where(Credential.user_id == user.id, Credential.provider == "hh")
    )
    cred = result.scalar_one_or_none()
    if cred:
        cred.encrypted_data = encrypted
        cred.status = "active"
    else:
        cred = Credential(
            user_id=user.id,
            provider="hh",
            status="active",
            encrypted_data=encrypted,
        )
        db.add(cred)

    await log_action(
        db, "credential_update", request=request, user_id=user.id,
        details={"provider": "hh", "method": "dev_code"},
    )
    await db.flush()

    return {"ok": True, "message": "HH аккаунт успешно подключён!"}


@router.delete("/api/account/credentials/hh")
async def delete_hh_credentials(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Credential).where(Credential.user_id == user.id, Credential.provider == "hh")
    )
    cred = result.scalar_one_or_none()
    if cred:
        await db.delete(cred)
        await log_action(db, "credential_delete", request=request, user_id=user.id, details={"provider": "hh"})
        await db.flush()
    return {"ok": True, "message": "HH аккаунт отключён"}


# --------------- LinkedIn Credentials ---------------

class LinkedInCredentialRequest(BaseModel):
    username: str
    password: str


@router.post("/api/account/credentials/linkedin")
async def save_linkedin_credentials(
    body: LinkedInCredentialRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import logging as _logging
    _logger = _logging.getLogger("app.api.account")

    data = {
        "username": body.username.strip(),
        "password": body.password,
    }

    # Headless Playwright login (same as create_session.py) → save cookies
    cookies_ok = False
    cookies_error = ""
    try:
        from app.services.linkedin_oauth import create_linkedin_cookies
        storage = await create_linkedin_cookies(data["username"], data["password"])
        data["cookies"] = storage
        cookies_ok = True
    except Exception as e:
        cookies_error = str(e)
        _logger.warning("LinkedIn headless login failed: %s", e)

    encrypted = encrypt_credentials(data)

    result = await db.execute(
        select(Credential).where(Credential.user_id == user.id, Credential.provider == "linkedin")
    )
    cred = result.scalar_one_or_none()
    if cred:
        cred.encrypted_data = encrypted
        cred.status = "active" if cookies_ok else "expired"
    else:
        cred = Credential(
            user_id=user.id,
            provider="linkedin",
            status="active" if cookies_ok else "expired",
            encrypted_data=encrypted,
        )
        db.add(cred)
    await log_action(
        db, "credential_update", request=request, user_id=user.id,
        details={"provider": "linkedin", "cookies_ok": cookies_ok},
    )
    await db.flush()

    if cookies_ok:
        return {"ok": True, "message": "LinkedIn подключён! Cookies сохранены."}
    else:
        return {
            "ok": True,
            "cookies_failed": True,
            "message": (
                f"Credentials сохранены, но авторизация не удалась: {cookies_error}. "
                "Поиск попробует авторизоваться автоматически."
            ),
        }


@router.delete("/api/account/credentials/linkedin")
async def delete_linkedin_credentials(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Credential).where(Credential.user_id == user.id, Credential.provider == "linkedin")
    )
    cred = result.scalar_one_or_none()
    if cred:
        await db.delete(cred)
        await log_action(db, "credential_delete", request=request, user_id=user.id, details={"provider": "linkedin"})
        await db.flush()
    return {"ok": True, "message": "LinkedIn credentials удалены"}


# --------------- Audit logs ---------------

@router.get("/api/account/logs")
async def get_logs(
    page: int = 1,
    per_page: int = 20,
    action: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get audit logs for the current user (admins see all)."""
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if not user.is_admin:
        query = query.where(AuditLog.user_id == user.id)
        count_query = count_query.where(AuditLog.user_id == user.id)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    # Total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginated results
    offset = (max(1, page) - 1) * per_page
    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "logs": [
            {
                "id": log.id,
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "ip_address": log.ip_address,
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
