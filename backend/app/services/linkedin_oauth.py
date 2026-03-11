"""LinkedIn authentication helpers: cookie creation and management.

Cookie-based auth uses Playwright (headless) to log in with real credentials
and capture browser cookies. These cookies are then used for Voyager API
requests and Playwright scraper fallback.

Playwright runs in a separate thread with its own event loop to avoid
asyncio subprocess NotImplementedError on Windows (uvicorn's ProactorEventLoop).
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from requests.cookies import RequestsCookieJar

from linkedin_api import BrowserManager, login_with_credentials

from app.core.security import decrypt_credentials

logger = logging.getLogger(__name__)

# Thread pool shared with linkedin_service for blocking work
_executor = ThreadPoolExecutor(max_workers=2)


# ── cookie helpers ────────────────────────────────────────────────

def cookies_from_storage(storage: dict) -> RequestsCookieJar:
    """Convert Playwright storage_state dict to ``RequestsCookieJar``."""
    jar = RequestsCookieJar()
    for c in storage.get("cookies", []):
        jar.set(
            c["name"],
            c["value"],
            domain=c.get("domain", ".linkedin.com"),
            path=c.get("path", "/"),
        )
    return jar


# ── Playwright-based cookie creation (headless) ──────────────────

def _create_cookies_in_thread(
    username: str,
    password: str,
    timeout_ms: int = 300_000,
) -> dict:
    """Run Playwright login in a dedicated thread with its own event loop.

    Flow: BrowserManager(headless) → login_with_credentials(warm_up=True)
    → context.storage_state() → cookies dict.

    Returns Playwright storage_state dict.
    """
    async def _do_login():
        async with BrowserManager(headless=True) as browser:
            await login_with_credentials(
                browser.page,
                email=username,
                password=password,
                timeout=timeout_ms,
            )
            return await browser.context.storage_state()

    return asyncio.run(_do_login())


async def create_linkedin_cookies(
    username: str,
    password: str,
    timeout_ms: int = 300_000,
) -> dict:
    """Create LinkedIn cookies via headless Playwright login.

    Runs in a separate thread to avoid Windows asyncio subprocess issues.
    Returns storage_state dict for DB persistence.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: _create_cookies_in_thread(username, password, timeout_ms),
    )


# ── credential decryption & cookie resolution ────────────────────

def resolve_cookies_from_credential(
    cred_encrypted: bytes,
) -> tuple[dict, str, str, Optional[RequestsCookieJar], Optional[dict]]:
    """Decrypt credential and extract cookies if available.

    Returns ``(raw_data, username, password, cookies_jar, cookies_storage)``.
    ``cookies_jar`` / ``cookies_storage`` may be ``None`` if no cookies saved yet.
    """
    try:
        data = decrypt_credentials(cred_encrypted)
    except Exception as e:
        logger.error("Failed to decrypt LinkedIn credentials: %s", e)
        raise ValueError("Invalid LinkedIn credentials") from e

    cookies_data = data.get("cookies")
    username = data.get("username", "")
    password = data.get("password", "")

    cookies_jar: Optional[RequestsCookieJar] = None
    cookies_storage: Optional[dict] = None

    if cookies_data:
        if isinstance(cookies_data, dict) and cookies_data.get("cookies"):
            cookies_jar = cookies_from_storage(cookies_data)
            cookies_storage = cookies_data
        elif isinstance(cookies_data, list):
            jar = RequestsCookieJar()
            for c in cookies_data:
                jar.set(
                    c.get("name", ""),
                    c.get("value", ""),
                    domain=c.get("domain", ".linkedin.com"),
                    path=c.get("path", "/"),
                )
            cookies_jar = jar
            cookies_storage = {"cookies": cookies_data}

    return data, username, password, cookies_jar, cookies_storage


async def ensure_cookies(
    cred_encrypted: bytes,
) -> tuple[RequestsCookieJar, Optional[dict], Optional[dict]]:
    """Get or create cookies from an encrypted LinkedIn credential.

    Returns ``(cookies_jar, cookies_storage, cookies_to_persist)``.
    ``cookies_to_persist`` is not None when fresh cookies were created and
    the caller should save them back to the credential record.
    """
    data, username, password, cookies_jar, cookies_storage = (
        resolve_cookies_from_credential(cred_encrypted)
    )
    cookies_to_persist: Optional[dict] = None

    if not cookies_jar and username and password:
        try:
            storage = await create_linkedin_cookies(username, password)
            cookies_jar = cookies_from_storage(storage)
            cookies_storage = storage
            cookies_to_persist = storage
            logger.info("Created fresh LinkedIn cookies via headless login")
        except Exception as e:
            raise ValueError(
                f"LinkedIn авторизация не удалась: {e}. "
                "Проверьте credentials в Личном кабинете."
            ) from e

    if not cookies_jar:
        raise ValueError(
            "LinkedIn не подключён. Перейдите в Личный кабинет."
        )

    return cookies_jar, cookies_storage, cookies_to_persist
