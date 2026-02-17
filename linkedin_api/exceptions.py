"""
Unified exception hierarchy for LinkedIn API and scraper.

Combines exceptions from open_linkedin_api and linkedin_scraper
into a single hierarchy under LinkedInError.
"""


class LinkedInError(Exception):
    """Base exception for all LinkedIn operations."""


# ── API exceptions (HTTP / Voyager) ──────────────────────────────

class LinkedInRequestError(LinkedInError):
    """LinkedIn API request returned a non-2xx status."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Request failed ({status_code}): {message}")


class ChallengeError(LinkedInError):
    """LinkedIn presented a challenge (CAPTCHA, email verify, etc.)."""


class UnauthorizedError(LinkedInError):
    """Authentication failed or session is invalid."""


# ── Browser / scraper exceptions ─────────────────────────────────

class AuthenticationError(LinkedInError):
    """Browser-based authentication failed."""


class RateLimitError(LinkedInError):
    """Rate limiting detected."""

    def __init__(self, message: str, suggested_wait_time: int = 300):
        super().__init__(message)
        self.suggested_wait_time = suggested_wait_time


class ScrapingError(LinkedInError):
    """Scraping a profile page failed."""


class ElementNotFoundError(LinkedInError):
    """Expected page element not found."""


class ProfileNotFoundError(LinkedInError):
    """Profile returned 404."""


class NetworkError(LinkedInError):
    """Network-level error (browser startup, connectivity, etc.)."""
