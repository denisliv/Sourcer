"""
linkedin_api — unified module for LinkedIn API and browser scraping.

Provides:
    Linkedin          — Voyager API (search, get_profile) via cookies
    BrowserManager    — Playwright browser lifecycle
    PersonScraper     — scrape full profile pages in a live browser
    login_with_credentials / login_with_cookie — browser auth helpers

Typical usage:

    # 1. Create session (once)
    from linkedin_api import BrowserManager, login_with_credentials
    async with BrowserManager(headless=False) as browser:
        await login_with_credentials(browser.page, email="...", password="...")
        await browser.save_session("linkedin_session.json")

    # 2. Search candidates
    from linkedin_api import Linkedin
    api = Linkedin(cookies=load_cookies("linkedin_session.json"))
    results = api.search_people(keyword_title="python developer", limit=10)

    # 3. Scrape a candidate's full profile
    from linkedin_api import BrowserManager, PersonScraper
    async with BrowserManager() as browser:
        await browser.load_session("linkedin_session.json")
        scraper = PersonScraper(browser.page)
        person = await scraper.scrape("https://www.linkedin.com/in/username/")
"""

from .linkedin import Linkedin
from .browser import (
    BrowserManager,
    is_logged_in,
    login_with_cookie,
    login_with_credentials,
)
from .scraper import PersonScraper, PeopleSearchScraper
from .models import (
    Accomplishment,
    Contact,
    Education,
    Experience,
    Interest,
    PeopleSearchResponse,
    PeopleSearchResult,
    Person,
)
from .exceptions import (
    AuthenticationError,
    ChallengeError,
    ElementNotFoundError,
    LinkedInError,
    LinkedInRequestError,
    NetworkError,
    ProfileNotFoundError,
    RateLimitError,
    ScrapingError,
    UnauthorizedError,
)

__all__ = [
    # Core
    "Linkedin",
    "BrowserManager",
    "PersonScraper",
    "PeopleSearchScraper",
    # Auth
    "login_with_credentials",
    "login_with_cookie",
    "is_logged_in",
    # Models
    "Person",
    "Experience",
    "Education",
    "Contact",
    "Accomplishment",
    "Interest",
    "PeopleSearchResult",
    "PeopleSearchResponse",
    # Exceptions
    "LinkedInError",
    "LinkedInRequestError",
    "ChallengeError",
    "UnauthorizedError",
    "AuthenticationError",
    "RateLimitError",
    "ScrapingError",
    "ElementNotFoundError",
    "ProfileNotFoundError",
    "NetworkError",
]
