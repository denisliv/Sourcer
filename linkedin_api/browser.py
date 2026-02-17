"""
Playwright-based browser management and LinkedIn authentication.

Combines BrowserManager + auth functions from linkedin_scraper
into a single module. Used for:
  - Creating sessions (login + save cookies)
  - Scraping profile pages (PersonScraper needs a live page)
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from .exceptions import AuthenticationError, NetworkError, RateLimitError

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  BrowserManager — async context manager for Playwright lifecycle
# ═══════════════════════════════════════════════════════════════════

class BrowserManager:
    """Manages Playwright browser lifecycle as an async context manager."""

    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
        **launch_options: Any,
    ):
        self.headless = headless
        self.slow_mo = slow_mo
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.user_agent = user_agent
        self.launch_options = launch_options

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
                **self.launch_options,
            )
            ctx_opts: Dict[str, Any] = {"viewport": self.viewport}
            if self.user_agent:
                ctx_opts["user_agent"] = self.user_agent
            self._context = await self._browser.new_context(**ctx_opts)
            self._page = await self._context.new_page()
            logger.info("Browser launched (headless=%s)", self.headless)
        except Exception as e:
            await self.close()
            raise NetworkError(f"Failed to start browser: {e}")

    async def close(self) -> None:
        for resource in (self._page, self._context, self._browser):
            if resource:
                try:
                    await resource.close()
                except Exception as e:
                    logger.error("Error closing resource: %s", e)
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.error("Error stopping playwright: %s", e)
        self._page = self._context = self._browser = self._playwright = None
        logger.info("Browser closed")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not started. Use `async with BrowserManager()`.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Browser context not initialized.")
        return self._context

    async def new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("Browser context not initialized.")
        return await self._context.new_page()

    async def save_session(self, filepath: str) -> None:
        """Save cookies + storage state to a JSON file."""
        if not self._context:
            raise RuntimeError("No browser context to save")
        storage = await self._context.storage_state()
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(storage, f, indent=2)
        logger.info("Session saved to %s", filepath)

    async def load_session(self, filepath: str) -> None:
        """Restore session from a previously saved JSON file."""
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Session file not found: {filepath}")
        if self._context:
            await self._context.close()
        if not self._browser:
            raise RuntimeError("Browser not started")
        self._context = await self._browser.new_context(
            storage_state=filepath,
            viewport=self.viewport,
            user_agent=self.user_agent,
        )
        if self._page:
            await self._page.close()
        self._page = await self._context.new_page()
        logger.info("Session loaded from %s", filepath)


# ═══════════════════════════════════════════════════════════════════
#  Authentication helpers
# ═══════════════════════════════════════════════════════════════════

async def warm_up_browser(page: Page) -> None:
    """Visit a few normal sites to look more human before hitting LinkedIn."""
    for url in ("https://www.google.com", "https://www.wikipedia.org"):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=10_000)
            await asyncio.sleep(1)
        except Exception:
            continue
    logger.info("Browser warm-up complete")


async def is_logged_in(page: Page) -> bool:
    """Check if the current page shows a logged-in LinkedIn session."""
    try:
        url = page.url
        blockers = ["/login", "/authwall", "/checkpoint", "/challenge", "/uas/login"]
        if any(b in url for b in blockers):
            return False

        sdui = await page.locator('[data-testid="primary-nav"]').count()
        old = await page.locator(
            '.global-nav__primary-link, [data-control-name="nav.settings"]'
        ).count()
        new = await page.locator(
            'nav a[href*="/feed"], nav button:has-text("Home"), nav a[href*="/mynetwork"]'
        ).count()
        if sdui > 0 or old > 0 or new > 0:
            return True

        auth_pages = ["/feed", "/mynetwork", "/messaging", "/notifications", "/in/"]
        return any(p in url for p in auth_pages)
    except Exception:
        return False


async def login_with_credentials(
    page: Page,
    email: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 30_000,
    warm_up: bool = True,
) -> None:
    """
    Log in to LinkedIn with email + password via Playwright.

    Handles 2FA / checkpoint by waiting for the user to complete it
    manually in the visible browser window.
    """
    if not email or not password:
        raise AuthenticationError("Email and password are required.")

    if warm_up:
        await warm_up_browser(page)

    logger.info("Logging in to LinkedIn...")

    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await _detect_rate_limit(page)

        try:
            await page.wait_for_selector("#username", timeout=timeout, state="visible")
        except PlaywrightTimeoutError:
            raise AuthenticationError("Login form not found.")

        await page.fill("#username", email)
        await page.fill("#password", password)
        await page.click('button[type="submit"]')

        try:
            await page.wait_for_url(
                lambda u: "feed" in u or "checkpoint" in u or "authwall" in u,
                timeout=timeout,
            )
        except PlaywrightTimeoutError:
            if "login" in page.url:
                raise AuthenticationError("Login failed — page did not navigate.")

        url = page.url

        if "authwall" in url:
            raise AuthenticationError(f"Auth wall encountered: {url}")

        if "checkpoint" in url or "challenge" in url:
            logger.warning("2FA / checkpoint detected, waiting for manual completion...")
            print("\n" + "=" * 60)
            print("  2FA / Security checkpoint required!")
            print("  Complete verification in the browser window.")
            print(f"  Waiting up to {timeout // 1000}s ...")
            print("=" * 60 + "\n")

            start = time.time()
            while (time.time() - start) * 1000 < timeout:
                if not any(
                    p in page.url for p in ("checkpoint", "challenge", "login", "authwall")
                ):
                    break
                await asyncio.sleep(1)
            else:
                raise AuthenticationError("Timed out waiting for 2FA.")

        # Poll to confirm login
        start = time.time()
        while (time.time() - start) * 1000 < 10_000:
            if await is_logged_in(page):
                logger.info("Successfully logged in.")
                return
            await asyncio.sleep(0.5)

        logger.warning("Could not verify login via nav element — proceeding anyway.")

    except AuthenticationError:
        raise
    except PlaywrightTimeoutError as e:
        raise AuthenticationError(f"Login timed out: {e}")
    except Exception as e:
        raise AuthenticationError(f"Unexpected login error: {e}")


async def login_with_cookie(page: Page, cookie_value: str) -> None:
    """Log in using a raw li_at cookie value."""
    logger.info("Logging in with li_at cookie...")
    try:
        await page.context.add_cookies([{
            "name": "li_at",
            "value": cookie_value,
            "domain": ".linkedin.com",
            "path": "/",
        }])
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        if "login" in page.url or "authwall" in page.url:
            raise AuthenticationError("Cookie login failed — cookie may be expired.")
        start = time.time()
        while (time.time() - start) * 1000 < 5_000:
            if await is_logged_in(page):
                logger.info("Cookie login successful.")
                return
            await asyncio.sleep(0.5)
        logger.warning("Could not verify cookie login — proceeding anyway.")
    except AuthenticationError:
        raise
    except Exception as e:
        raise AuthenticationError(f"Cookie auth error: {e}")


# ═══════════════════════════════════════════════════════════════════
#  Page-level utilities (used by scrapers)
# ═══════════════════════════════════════════════════════════════════

async def _detect_rate_limit(page: Page) -> None:
    """Raise RateLimitError if LinkedIn is blocking us."""
    url = page.url
    if "checkpoint" in url or "authwall" in url:
        raise RateLimitError("LinkedIn security checkpoint detected.", 3600)
    try:
        captcha = await page.locator('iframe[title*="captcha" i]').count()
        if captcha > 0:
            raise RateLimitError("CAPTCHA detected.", 3600)
    except Exception:
        pass
    try:
        body = await page.locator("body").text_content(timeout=1000)
        if body and any(p in body.lower() for p in ("too many requests", "rate limit", "try again later")):
            raise RateLimitError("Rate-limit message detected.", 1800)
    except PlaywrightTimeoutError:
        pass


async def scroll_to_bottom(page: Page, pause: float = 1.0, max_scrolls: int = 10) -> None:
    for _ in range(max_scrolls):
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause)
        if await page.evaluate("document.body.scrollHeight") == prev:
            break


async def scroll_to_half(page: Page) -> None:
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")


async def extract_text_safe(page: Page, selector: str, default: str = "", timeout: float = 2000) -> str:
    try:
        el = page.locator(selector).first
        text = await el.text_content(timeout=timeout)
        return text.strip() if text else default
    except Exception:
        return default


async def click_see_more_buttons(page: Page, max_attempts: int = 10) -> int:
    clicked = 0
    for _ in range(max_attempts):
        try:
            btn = page.locator(
                'button:has-text("See more"), button:has-text("Show more"), button:has-text("show all")'
            ).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await asyncio.sleep(0.5)
                clicked += 1
            else:
                break
        except Exception:
            break
    return clicked


async def handle_modal_close(page: Page) -> bool:
    try:
        btn = page.locator(
            'button[aria-label="Dismiss"], button[aria-label="Close"], button.artdeco-modal__dismiss'
        ).first
        if await btn.is_visible(timeout=1000):
            await btn.click()
            await asyncio.sleep(0.5)
            return True
    except Exception:
        pass
    return False
