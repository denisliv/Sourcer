"""
LinkedIn search service.

Search logic for LinkedIn: Voyager API (primary) with Playwright scraper
fallback.  Authentication and cookie management live in ``linkedin_oauth``.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from requests.cookies import RequestsCookieJar

from linkedin_api import BrowserManager, Linkedin, PeopleSearchScraper

from app.core.config import HH_AREAS_DICT
from app.core.security import decrypt_credentials
from app.services.linkedin_oauth import (
    _executor,
    cookies_from_storage,
    create_linkedin_cookies,
    ensure_cookies,
)

logger = logging.getLogger(__name__)


# ── LinkedIn API search (sync, runs in executor) ─────────────────

def search_linkedin_sync(
    cookies_jar: RequestsCookieJar,
    keyword_title: str = "",
    keywords: str = "",
    limit: int = 50,
) -> list[dict]:
    """Search LinkedIn via Voyager API (primary method)."""
    api = Linkedin(cookies=cookies_jar)
    kw_title = keyword_title.strip() or None
    kw = keywords.strip() or None
    if not kw_title and not kw:
        return []

    try:
        results = api.search_people(
            keyword_title=kw_title,
            keywords=kw,
            include_private_profiles=True,
            limit=min(limit, 100),
        )
    except Exception as e:
        logger.warning("LinkedIn API search failed: %s", e)
        raise

    candidates = []
    for r in results:
        name = r.get("name") or "—"
        jobtitle = r.get("jobtitle") or "—"
        location = r.get("location") or "—"
        nav = r.get("navigation_url") or ""
        if nav and not nav.startswith("http"):
            nav = (
                f"https://www.linkedin.com{nav}"
                if nav.startswith("/")
                else f"https://www.linkedin.com/in/{nav}"
            )
        candidates.append({
            "source": "linkedin",
            "photo": None,
            "full_name": name,
            "title": jobtitle,
            "area": location,
            "experience": "—",
            "salary": "—",
            "url": nav,
            "updated_at": "—",
            "fetched_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "urn_id": r.get("urn_id"),
        })
    return candidates


# ── Playwright scraper fallback (runs in thread) ─────────────────

def _search_linkedin_scraper_in_thread(
    cookies_storage: dict,
    keyword_title: str,
    keywords: str,
    limit: int,
) -> list[dict]:
    """Run Playwright scraper in a dedicated thread (Windows fix)."""
    async def _do_scrape():
        location = keywords.strip().split(",")[0].strip() if keywords else ""
        search_kw = keyword_title.strip()
        if keywords and keyword_title:
            search_kw = f"{keyword_title} {keywords}"
        elif not search_kw:
            search_kw = keywords

        async with BrowserManager(headless=True) as browser:
            import tempfile
            with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w",
            ) as f:
                json.dump(cookies_storage, f, indent=2)
                path = f.name
            try:
                await browser.load_session(path)
            finally:
                Path(path).unlink(missing_ok=True)

            scraper = PeopleSearchScraper(browser.page)
            response = await scraper.search(
                keywords=search_kw,
                location=location or "Беларусь",
                max_pages=max(1, (limit + 9) // 10),
            )

        candidates = []
        for p in (response.results or [])[:limit]:
            candidates.append({
                "source": "linkedin",
                "photo": None,
                "full_name": getattr(p, "name", None) or "—",
                "title": getattr(p, "headline", None) or "—",
                "area": "—",
                "experience": "—",
                "salary": "—",
                "url": getattr(p, "linkedin_url", "") or "—",
                "updated_at": "—",
                "fetched_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "urn_id": None,
            })
        return candidates

    return asyncio.run(_do_scrape())


# ── main entry point ─────────────────────────────────────────────

async def search_linkedin(
    cred_encrypted: bytes,
    search_text: str,
    search_skills: str,
    area: int,
    count: int,
) -> tuple[list[dict], Optional[dict]]:
    """Get cookies from credential, run search.

    Returns ``(candidates, cookies_to_persist)``.
    When ``cookies_to_persist`` is not None the caller should save them
    back to the credential record in the DB.
    """
    cookies_jar, cookies_storage, cookies_to_persist = await ensure_cookies(
        cred_encrypted
    )

    # Build LinkedIn params from UI
    keyword_title = search_text.strip()
    location_name = HH_AREAS_DICT.get(area, "Беларусь")
    keywords_parts = [location_name]
    if search_skills.strip():
        skills_clean = " ".join(
            s.strip() for s in search_skills.split(",") if s.strip()
        )
        if skills_clean:
            keywords_parts.append(skills_clean)
    keywords = " ".join(keywords_parts) if keywords_parts else ""

    # Run Voyager API in thread (it's synchronous)
    loop = asyncio.get_running_loop()
    try:
        candidates = await loop.run_in_executor(
            None,
            lambda: search_linkedin_sync(
                cookies_jar=cookies_jar,
                keyword_title=keyword_title,
                keywords=keywords,
                limit=count,
            ),
        )
        return candidates, cookies_to_persist
    except Exception as api_err:
        logger.warning(
            "LinkedIn API failed: %s. Attempting cookie refresh...", api_err
        )
        # Try refresh: expired cookies often cause API errors
        new_storage: Optional[dict] = None
        try:
            data = decrypt_credentials(cred_encrypted)
            username = (data.get("username") or "").strip()
            password = data.get("password", "")
            if username and password:
                new_storage = await create_linkedin_cookies(username, password)
                new_jar = cookies_from_storage(new_storage)
                logger.info("Refreshed LinkedIn cookies, retrying search")
                candidates = await loop.run_in_executor(
                    None,
                    lambda: search_linkedin_sync(
                        cookies_jar=new_jar,
                        keyword_title=keyword_title,
                        keywords=keywords,
                        limit=count,
                    ),
                )
                return candidates, new_storage
        except Exception as refresh_err:
            logger.warning(
                "LinkedIn cookie refresh failed: %s. Trying scraper fallback.",
                refresh_err,
            )

        # Fallback to scraper (use new cookies if we have them)
        storage_for_scraper = new_storage or cookies_storage
        if storage_for_scraper:
            try:
                candidates = await loop.run_in_executor(
                    _executor,
                    _search_linkedin_scraper_in_thread,
                    storage_for_scraper,
                    keyword_title,
                    keywords,
                    count,
                )
                return candidates, new_storage if new_storage else None
            except Exception as scrape_err:
                logger.warning("LinkedIn scraper fallback failed: %s", scrape_err)

        raise ValueError(
            f"Ошибка поиска LinkedIn: {api_err}"
        ) from api_err
