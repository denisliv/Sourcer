"""
Low-level HTTP client for LinkedIn Voyager API.

Handles session management, CSRF tokens, rate limiting,
and cookie-based authentication.  Adapted from open_linkedin_api.
"""

import json
import logging

import requests
from bs4 import BeautifulSoup, Tag
from requests.cookies import RequestsCookieJar

from .exceptions import (
    ChallengeError,
    LinkedInRequestError,
    UnauthorizedError,
)
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class Client:
    """HTTP client for the LinkedIn Voyager API."""

    LINKEDIN_BASE_URL = "https://www.linkedin.com"
    API_BASE_URL = f"{LINKEDIN_BASE_URL}/voyager/api"

    REQUEST_HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "accept-language": "en-AU,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
    }

    AUTH_REQUEST_HEADERS = {
        "X-Li-User-Agent": "LIAuthLibrary:3.2.4 com.linkedin.LinkedIn:8.8.1 Chrome:131.0",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "X-User-Language": "en",
        "X-User-Locale": "en_US",
        "Accept-Language": "en-us",
    }

    def __init__(self, *, debug: bool = False, proxies: dict | None = None):
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.session.headers.update(self.REQUEST_HEADERS)
        self.proxies = proxies or {}
        self.metadata: dict = {}
        self.rate_limiter = RateLimiter(
            requests_per_minute=10,
            min_delay_seconds=3.0,
            max_delay_seconds=8.0,
            burst_size=3,
        )
        logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    # ── cookie helpers ───────────────────────────────────────────

    def set_cookies(self, cookies: RequestsCookieJar) -> None:
        """Set session cookies and extract CSRF token."""
        self.session.cookies = cookies
        self.session.headers["csrf-token"] = (
            self.session.cookies["JSESSIONID"].strip('"')
        )

    @property
    def cookies(self) -> RequestsCookieJar:
        return self.session.cookies

    # ── authentication ───────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> None:
        """Full username/password authentication flow."""
        initial_cookies = self._request_session_cookies()
        self.set_cookies(initial_cookies)

        payload = {
            "session_key": username,
            "session_password": password,
            "JSESSIONID": self.session.cookies["JSESSIONID"],
        }
        res = requests.post(
            f"{self.LINKEDIN_BASE_URL}/uas/authenticate",
            data=payload,
            cookies=self.session.cookies,
            headers=self.AUTH_REQUEST_HEADERS,
            proxies=self.proxies,
        )

        data = res.json()
        if data and data.get("login_result") != "PASS":
            raise ChallengeError(data.get("login_result", "UNKNOWN"))

        if res.status_code == 401:
            raise UnauthorizedError()
        if res.status_code != 200:
            raise LinkedInRequestError(res.status_code, res.text[:200])

        self.set_cookies(res.cookies)
        self._fetch_metadata()

    # ── internal ─────────────────────────────────────────────────

    def _request_session_cookies(self) -> RequestsCookieJar:
        res = requests.get(
            f"{self.LINKEDIN_BASE_URL}/uas/authenticate",
            headers=self.AUTH_REQUEST_HEADERS,
            proxies=self.proxies,
        )
        return res.cookies

    def _fetch_metadata(self) -> None:
        res = requests.get(
            self.LINKEDIN_BASE_URL,
            cookies=self.session.cookies,
            headers=self.AUTH_REQUEST_HEADERS,
            proxies=self.proxies,
        )
        soup = BeautifulSoup(res.text, "lxml")

        tag = soup.find("meta", attrs={"name": "applicationInstance"})
        if tag and isinstance(tag, Tag):
            raw = tag.attrs.get("content", "{}")
            self.metadata["clientApplicationInstance"] = json.loads(raw)

        tag = soup.find("meta", attrs={"name": "clientPageInstanceId"})
        if tag and isinstance(tag, Tag):
            self.metadata["clientPageInstanceId"] = tag.attrs.get("content")
