"""HeadHunter OAuth2 helpers: token exchange, refresh, and expiry checks."""

from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import HH_CLIENT_ID, HH_CLIENT_SECRET, HH_REDIRECT_URI

HH_OAUTH_TOKEN_URL = "https://hh.ru/oauth/token"


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange an authorization code for access_token + refresh_token.

    Returns dict with keys: access_token, token_type, refresh_token, expires_in.
    Raises ``httpx.HTTPStatusError`` on failure.
    """
    body = {
        "grant_type": "authorization_code",
        "client_id": HH_CLIENT_ID,
        "client_secret": HH_CLIENT_SECRET,
        "code": code,
        "redirect_uri": HH_REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(HH_OAUTH_TOKEN_URL, data=body)
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Use a refresh_token to obtain a new access_token.

    Returns dict with keys: access_token, token_type, refresh_token, expires_in.
    Raises ``httpx.HTTPStatusError`` on failure.
    """
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(HH_OAUTH_TOKEN_URL, data=body)
        resp.raise_for_status()
        return resp.json()


def compute_expires_at(expires_in: int) -> str:
    """Convert ``expires_in`` (seconds) to an ISO-8601 UTC timestamp string."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return dt.isoformat()


def is_token_expired(expires_at_iso: str | None, buffer_seconds: int = 300) -> bool:
    """Return ``True`` if the token is expired or will expire within *buffer_seconds*."""
    if not expires_at_iso:
        return True
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
        return datetime.now(timezone.utc) >= (expires_at - timedelta(seconds=buffer_seconds))
    except (ValueError, TypeError):
        return True
