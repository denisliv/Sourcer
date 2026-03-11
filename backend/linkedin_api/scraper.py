"""
Playwright-based scrapers for LinkedIn.

PersonScraper — full profile parsing (Experience, Education, etc.)
PeopleSearchScraper — search results page parsing (name, headline, URL)

Both work with a live browser session (Playwright Page) and support
LinkedIn SDUI 2025+ layout.
"""

import asyncio
import logging
import re
import time
from typing import List, Optional
from urllib.parse import urlencode, urljoin

from playwright.async_api import Page

from .browser import (
    _detect_rate_limit,
    extract_text_safe,
    is_logged_in,
    scroll_to_bottom,
    scroll_to_half,
)
from .exceptions import AuthenticationError, ScrapingError
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

logger = logging.getLogger(__name__)

# Multi-language section heading variants for LinkedIn SDUI
_HEADING_ABOUT = {
    "About",
    "Общие сведения",
    "Acerca de",
    "À propos",
    "Info",
    "Informazioni",
    "Über",
    "关于",
    "소개",
}
_HEADING_EXPERIENCE = {
    "Experience",
    "Опыт работы",
    "Experiencia",
    "Expérience",
    "Berufserfahrung",
    "Esperienza",
    "工作经历",
    "경력",
}
_HEADING_EDUCATION = {
    "Education",
    "Образование",
    "Educación",
    "Formation",
    "Ausbildung",
    "Istruzione",
    "教育背景",
    "학력",
}
_HEADING_INTERESTS = {
    "Interests",
    "Интересы",
    "Intereses",
    "Centres d'intérêt",
    "Interessen",
    "Interessi",
    "兴趣",
    "관심사",
}


class PersonScraper:
    """Async scraper for LinkedIn person profiles."""

    def __init__(self, page: Page):
        self.page = page

    # ── public API ───────────────────────────────────────────────

    async def scrape(self, linkedin_url: str) -> Person:
        """
        Scrape a full LinkedIn profile.

        Args:
            linkedin_url: URL like https://www.linkedin.com/in/username/

        Returns:
            Person model with all available sections.
        """
        try:
            await self._navigate(linkedin_url)
            await self._ensure_logged_in()
            await self.page.wait_for_selector("main", timeout=10_000)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            await asyncio.sleep(2)

            name, location = await self._get_name_and_location()
            open_to_work = await self._check_open_to_work()
            about = await self._get_about()

            await scroll_to_half(self.page)
            await scroll_to_bottom(self.page, pause=0.5, max_scrolls=3)

            experiences = await self._get_experiences(linkedin_url)
            educations = await self._get_educations(linkedin_url)
            interests = await self._get_interests(linkedin_url)
            accomplishments = await self._get_accomplishments(linkedin_url)
            contacts = await self._get_contacts(linkedin_url)

            return Person(
                linkedin_url=linkedin_url,
                name=name,
                location=location,
                about=about,
                open_to_work=open_to_work,
                experiences=experiences,
                educations=educations,
                interests=interests,
                accomplishments=accomplishments,
                contacts=contacts,
            )
        except Exception as e:
            raise ScrapingError(f"Failed to scrape profile: {e}")

    # ── navigation / auth ────────────────────────────────────────

    async def _navigate(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await _detect_rate_limit(self.page)

    async def _ensure_logged_in(self, timeout: float = 10.0) -> None:
        start = time.time()
        while time.time() - start < timeout:
            if await is_logged_in(self.page):
                return
            await asyncio.sleep(0.5)
        raise AuthenticationError("Not logged in. Authenticate before scraping.")

    # ── section helpers ──────────────────────────────────────────

    async def _find_section_by_heading(self, headings: set):
        sections = await self.page.locator("main section").all()
        for section in sections:
            h2 = section.locator("h2").first
            if await h2.count() > 0:
                text = await h2.text_content(timeout=2000)
                if text and text.strip() in headings:
                    return section
        return None

    # ── name & location ──────────────────────────────────────────

    async def _get_name_and_location(self) -> tuple[str, Optional[str]]:
        try:
            name = "Unknown"
            location = None

            first = self.page.locator("main section").first
            if await first.count() > 0:
                h2 = first.locator("h2").first
                if await h2.count() > 0:
                    t = await h2.text_content(timeout=5000)
                    if t and t.strip():
                        name = t.strip()

            if name == "Unknown":
                name = await extract_text_safe(self.page, "h1", default="Unknown")

            if await first.count() > 0:
                p_tags = await first.locator("p").all()
                for i, p in enumerate(p_tags):
                    text = await p.text_content(timeout=2000)
                    if text and text.strip() == "\u00b7" and i > 0:
                        prev = await p_tags[i - 1].text_content(timeout=2000)
                        if prev:
                            location = prev.strip()
                        break

            if not location:
                loc = await extract_text_safe(
                    self.page, ".text-body-small.inline.t-black--light.break-words"
                )
                location = loc or None

            return name, location
        except Exception as e:
            logger.warning("Error getting name/location: %s", e)
            return "Unknown", None

    async def _check_open_to_work(self) -> bool:
        try:
            title = await self._get_attr(".pv-top-card-profile-picture img", "title")
            return "#OPEN_TO_WORK" in title.upper()
        except Exception:
            return False

    # ── about ────────────────────────────────────────────────────

    async def _get_about(self) -> Optional[str]:
        try:
            section = await self._find_section_by_heading(_HEADING_ABOUT)
            if section:
                exp = section.locator('[data-testid="expandable-text-box"]').first
                if await exp.count() > 0:
                    text = await exp.text_content(timeout=5000)
                    return text.strip() if text else None

            cards = await self.page.locator('[data-view-name="profile-card"]').all()
            for card in cards:
                ct = await card.inner_text()
                if ct.strip().startswith("About"):
                    spans = await card.locator('span[aria-hidden="true"]').all()
                    if len(spans) > 1:
                        t = await spans[1].text_content()
                        return t.strip() if t else None
            return None
        except Exception:
            return None

    # ── experience ───────────────────────────────────────────────

    async def _get_experiences(self, base_url: str) -> list[Experience]:
        experiences: list[Experience] = []
        try:
            container = self.page.locator(
                '[data-testid*="ExperienceTopLevelSection"]'
            ).first
            if await container.count() > 0:
                items = await container.locator(":scope > div").all()
                for item in items:
                    exp = await self._parse_main_experience(item)
                    if exp:
                        experiences.append(exp)

            if not experiences:
                section = await self._find_section_by_heading(_HEADING_EXPERIENCE)
                if section:
                    items = await section.locator("ul > li, ol > li").all()
                    for item in items:
                        exp = await self._parse_main_experience(item)
                        if exp:
                            experiences.append(exp)

            if not experiences:
                url = urljoin(base_url, "details/experience")
                await self._navigate(url)
                await self.page.wait_for_selector("main", timeout=10_000)
                await asyncio.sleep(1.5)
                await scroll_to_half(self.page)
                await scroll_to_bottom(self.page, pause=0.5, max_scrolls=5)

                main = self.page.locator("main")
                items = []
                if await main.count() > 0:
                    items = await main.locator("list > listitem, ul > li").all()
                if not items:
                    old_list = self.page.locator(".pvs-list__container").first
                    if await old_list.count() > 0:
                        items = await old_list.locator(
                            ".pvs-list__paged-list-item"
                        ).all()

                for item in items:
                    result = await self._parse_detail_experience(item)
                    if isinstance(result, list):
                        experiences.extend(result)
                    elif result:
                        experiences.append(result)
        except Exception as e:
            logger.warning("Error getting experiences: %s", e)
        return experiences

    async def _parse_main_experience(self, item) -> Optional[Experience]:
        try:
            p_tags = await item.locator("p").all()
            texts = []
            for p in p_tags:
                t = await p.text_content(timeout=2000)
                if t:
                    texts.append(t.strip())
            if len(texts) < 2:
                return None

            position = texts[0]
            company = texts[1].split(" \u00b7 ")[0].strip()
            work_times = texts[2] if len(texts) > 2 else ""
            from_d, to_d, dur = self._parse_work_times(work_times)
            loc_raw = texts[3] if len(texts) > 3 else ""
            loc = loc_raw.split(" \u00b7 ")[0].strip() if loc_raw else ""

            desc = None
            exp_box = item.locator('[data-testid="expandable-text-box"]').first
            if await exp_box.count() > 0:
                dt = await exp_box.text_content(timeout=2000)
                desc = dt.strip() if dt else None

            company_url = None
            links = await item.locator("a").all()
            if links:
                company_url = await links[0].get_attribute("href")

            return Experience(
                position_title=position,
                institution_name=company,
                linkedin_url=company_url,
                from_date=from_d,
                to_date=to_d,
                duration=dur,
                location=loc,
                description=desc,
            )
        except Exception:
            return None

    async def _parse_detail_experience(self, item):
        try:
            links = await item.locator("a, link").all()
            if len(links) >= 2:
                company_url = await links[0].get_attribute("href")
                detail = links[1]
                generics = await detail.locator("generic, span, div").all()
                texts = []
                for g in generics:
                    t = await g.text_content()
                    if t and t.strip() and len(t.strip()) < 200:
                        texts.append(t.strip())
                unique = list(dict.fromkeys(texts))
                if len(unique) >= 2:
                    from_d, to_d, dur = self._parse_work_times(
                        unique[2] if len(unique) > 2 else ""
                    )
                    return Experience(
                        position_title=unique[0],
                        institution_name=unique[1],
                        linkedin_url=company_url,
                        from_date=from_d,
                        to_date=to_d,
                        duration=dur,
                        location=unique[3] if len(unique) > 3 else "",
                    )
            return None
        except Exception:
            return None

    # ── education ────────────────────────────────────────────────

    async def _get_educations(self, base_url: str) -> list[Education]:
        educations: list[Education] = []
        try:
            section = await self._find_section_by_heading(_HEADING_EDUCATION)
            if section:
                p_tags = await section.locator("p").all()
                p_texts = []
                for p in p_tags:
                    t = await p.text_content(timeout=2000)
                    if t and t.strip():
                        p_texts.append(t.strip())

                groups: list[list[str]] = []
                current: list[str] = []
                for text in p_texts:
                    current.append(text)
                    if self._looks_like_date(text):
                        groups.append(current)
                        current = []

                for group in groups:
                    edu = self._education_from_group(group)
                    if edu:
                        educations.append(edu)

            if not educations:
                url = urljoin(base_url, "details/education")
                await self._navigate(url)
                await self.page.wait_for_selector("main", timeout=10_000)
                await asyncio.sleep(2)
                await scroll_to_half(self.page)
                await scroll_to_bottom(self.page, pause=0.5, max_scrolls=5)

                main = self.page.locator("main")
                items = []
                if await main.count() > 0:
                    items = await main.locator("ul > li, ol > li").all()
                if not items:
                    old_list = self.page.locator(".pvs-list__container").first
                    if await old_list.count() > 0:
                        items = await old_list.locator(
                            ".pvs-list__paged-list-item"
                        ).all()

                for item in items:
                    edu = await self._parse_detail_education(item)
                    if edu:
                        educations.append(edu)
        except Exception as e:
            logger.warning("Error getting educations: %s", e)
        return educations

    async def _parse_detail_education(self, item) -> Optional[Education]:
        try:
            links = await item.locator("a, link").all()
            if len(links) >= 1:
                inst_url = await links[0].get_attribute("href")
                detail = links[1] if len(links) >= 2 else links[0]
                generics = await detail.locator("generic, span, div").all()
                texts = []
                for g in generics:
                    t = await g.text_content()
                    if t and t.strip() and len(t.strip()) < 200:
                        texts.append(t.strip())
                unique = list(dict.fromkeys(texts))
                if unique:
                    inst = unique[0]
                    degree = None
                    times = ""
                    if len(unique) == 3:
                        degree = unique[1]
                        times = unique[2]
                    elif len(unique) == 2:
                        second = unique[1]
                        if " - " in second or any(c.isdigit() for c in second):
                            times = second
                        else:
                            degree = second
                    from_d, to_d = self._parse_edu_times(times)
                    return Education(
                        institution_name=inst,
                        degree=degree.strip() if degree else None,
                        linkedin_url=inst_url,
                        from_date=from_d,
                        to_date=to_d,
                    )
            return None
        except Exception:
            return None

    # ── interests ────────────────────────────────────────────────

    async def _get_interests(self, base_url: str) -> list[Interest]:
        interests: list[Interest] = []
        try:
            section = await self._find_section_by_heading(_HEADING_INTERESTS)
            if section:
                tabs = await section.locator('[role="tab"], tab').all()
                for tab in tabs:
                    try:
                        tab_name = await tab.text_content()
                        if not tab_name:
                            continue
                        category = self._interest_category(tab_name.strip())
                        await tab.click()
                        await asyncio.sleep(0.5)
                        panel = section.locator('[role="tabpanel"]').first
                        if await panel.count() > 0:
                            items = await panel.locator("li, listitem").all()
                            for item in items:
                                interest = await self._parse_interest(item, category)
                                if interest:
                                    interests.append(interest)
                    except Exception:
                        continue

            if not interests:
                url = urljoin(base_url, "details/interests/")
                await self._navigate(url)
                await self.page.wait_for_selector("main", timeout=10_000)
                await asyncio.sleep(1.5)
                tabs = await self.page.locator('[role="tab"], tab').all()
                for tab in tabs:
                    try:
                        tab_name = await tab.text_content()
                        if not tab_name:
                            continue
                        category = self._interest_category(tab_name.strip())
                        await tab.click()
                        await asyncio.sleep(0.8)
                        panel = self.page.locator('[role="tabpanel"], tabpanel').first
                        items = await panel.locator(
                            "listitem, li, .pvs-list__paged-list-item"
                        ).all()
                        for item in items:
                            interest = await self._parse_interest(item, category)
                            if interest:
                                interests.append(interest)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Error getting interests: %s", e)
        return interests

    async def _parse_interest(self, item, category: str) -> Optional[Interest]:
        try:
            link = item.locator("a, link").first
            if await link.count() == 0:
                return None
            href = await link.get_attribute("href")
            texts = await self._unique_texts(item)
            name = texts[0] if texts else None
            if name and href:
                return Interest(name=name, category=category, linkedin_url=href)
            return None
        except Exception:
            return None

    # ── accomplishments ──────────────────────────────────────────

    async def _get_accomplishments(self, base_url: str) -> list[Accomplishment]:
        accomplishments: list[Accomplishment] = []
        sections = [
            ("certifications", "certification"),
            ("honors", "honor"),
            ("publications", "publication"),
            ("patents", "patent"),
            ("courses", "course"),
            ("projects", "project"),
            ("languages", "language"),
            ("organizations", "organization"),
        ]
        for url_path, category in sections:
            try:
                url = urljoin(base_url, f"details/{url_path}/")
                await self._navigate(url)
                await self.page.wait_for_selector("main", timeout=10_000)
                await asyncio.sleep(1)

                if await self.page.locator('text="Nothing to see for now"').count() > 0:
                    continue

                container = self.page.locator(
                    ".pvs-list__container, main ul, main ol"
                ).first
                if await container.count() == 0:
                    continue

                items = await container.locator(".pvs-list__paged-list-item").all()
                if not items:
                    items = await container.locator("> li").all()

                seen: set[str] = set()
                for item in items:
                    acc = await self._parse_accomplishment(item, category)
                    if acc and acc.title not in seen:
                        seen.add(acc.title)
                        accomplishments.append(acc)
            except Exception:
                continue
        return accomplishments

    async def _parse_accomplishment(
        self, item, category: str
    ) -> Optional[Accomplishment]:
        try:
            entity = item.locator(
                'div[data-view-name="profile-component-entity"]'
            ).first
            if await entity.count() > 0:
                spans = await entity.locator('span[aria-hidden="true"]').all()
            else:
                spans = await item.locator('span[aria-hidden="true"]').all()

            title = issuer = issued_date = cred_id = ""
            for i, span in enumerate(spans[:5]):
                t = await span.text_content()
                if not t or len(t.strip()) > 500:
                    continue
                t = t.strip()
                if i == 0:
                    title = t
                elif "Issued by" in t:
                    parts = t.split("·")
                    issuer = parts[0].replace("Issued by", "").strip()
                    if len(parts) > 1:
                        issued_date = parts[1].strip()
                elif "Issued " in t and not issued_date:
                    issued_date = t.replace("Issued ", "")
                elif "Credential ID" in t:
                    cred_id = t.replace("Credential ID ", "")
                elif i == 1 and not issuer:
                    issuer = t

            link = item.locator('a[href*="credential"], a[href*="verify"]').first
            cred_url = (
                await link.get_attribute("href") if await link.count() > 0 else None
            )

            if not title or len(title) > 200:
                return None

            return Accomplishment(
                category=category,
                title=title,
                issuer=issuer or None,
                issued_date=issued_date or None,
                credential_id=cred_id or None,
                credential_url=cred_url,
            )
        except Exception:
            return None

    # ── contacts ─────────────────────────────────────────────────

    async def _get_contacts(self, base_url: str) -> list[Contact]:
        contacts: list[Contact] = []
        try:
            url = urljoin(base_url, "overlay/contact-info/")
            await self._navigate(url)
            await asyncio.sleep(1)

            dialog = self.page.locator('dialog, [role="dialog"]').first
            if await dialog.count() == 0:
                return contacts

            headings = await dialog.locator("h3").all()
            for h in headings:
                try:
                    ht = await h.text_content()
                    if not ht:
                        continue
                    ctype = self._contact_type(ht.strip().lower())
                    if not ctype:
                        continue
                    container = h.locator("xpath=ancestor::*[1]")
                    if await container.count() == 0:
                        continue
                    links = await container.locator("a").all()
                    for link in links:
                        href = await link.get_attribute("href")
                        text = await link.text_content()
                        if href and text:
                            text = text.strip()
                            if ctype == "linkedin":
                                contacts.append(Contact(type=ctype, value=href))
                            elif ctype == "email" and "mailto:" in href:
                                contacts.append(
                                    Contact(
                                        type=ctype, value=href.replace("mailto:", "")
                                    )
                                )
                            else:
                                contacts.append(Contact(type=ctype, value=text))
                    if ctype in ("birthday", "phone", "address") and not links:
                        raw = await container.text_content()
                        if raw:
                            val = raw.replace(ht.strip(), "").strip()
                            if val:
                                contacts.append(Contact(type=ctype, value=val))
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Error getting contacts: %s", e)
        return contacts

    # ── utilities ─────────────────────────────────────────────────

    async def _get_attr(self, selector: str, attr: str, default: str = "") -> str:
        try:
            el = self.page.locator(selector).first
            val = await el.get_attribute(attr, timeout=2000)
            return val if val else default
        except Exception:
            return default

    async def _unique_texts(self, element) -> list[str]:
        els = await element.locator('span[aria-hidden="true"], div > span').all()
        if not els:
            els = await element.locator("span, div").all()
        seen: set[str] = set()
        result: list[str] = []
        for el in els:
            t = await el.text_content()
            if t and t.strip() and len(t.strip()) < 200:
                t = t.strip()
                if t not in seen and not any(
                    t in s or s in t for s in seen if len(s) > 3
                ):
                    seen.add(t)
                    result.append(t)
        return result

    @staticmethod
    def _parse_work_times(
        text: str,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not text:
            return None, None, None
        try:
            parts = text.split("\u00b7")
            times = parts[0].strip() if parts else ""
            duration = parts[1].strip() if len(parts) > 1 else None
            from_d = times
            to_d = ""
            for sep in (" \u2013 ", " – ", " - "):
                if sep in times:
                    dp = times.split(sep, 1)
                    from_d = dp[0].strip()
                    to_d = dp[1].strip() if len(dp) > 1 else ""
                    break
            return from_d, to_d, duration
        except Exception:
            return None, None, None

    @staticmethod
    def _looks_like_date(text: str) -> bool:
        return bool(re.search(r"\d{4}", text))

    def _education_from_group(self, group: list[str]) -> Optional[Education]:
        if not group:
            return None
        inst = group[0]
        degree = None
        times = ""
        if len(group) >= 3:
            degree = group[1]
            times = group[2]
        elif len(group) == 2:
            if self._looks_like_date(group[1]):
                times = group[1]
            else:
                degree = group[1]
        from_d, to_d = self._parse_edu_times(times)
        return Education(
            institution_name=inst,
            degree=degree.strip() if degree else None,
            from_date=from_d,
            to_date=to_d,
        )

    @staticmethod
    def _parse_edu_times(text: str) -> tuple[Optional[str], Optional[str]]:
        if not text:
            return None, None
        try:
            ru = re.match(r"[Сс]\s+(.+?)\s+по\s+(.+)", text)
            if ru:
                return ru.group(1).strip(), ru.group(2).strip()
            for sep in (" \u2013 ", " – ", " - "):
                if sep in text:
                    parts = text.split(sep, 1)
                    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
            return text.strip(), text.strip()
        except Exception:
            return None, None

    @staticmethod
    def _interest_category(name: str) -> str:
        n = name.lower()
        if "compan" in n:
            return "company"
        if "group" in n:
            return "group"
        if "school" in n:
            return "school"
        if "newsletter" in n:
            return "newsletter"
        if "voice" in n or "influencer" in n:
            return "influencer"
        return n

    @staticmethod
    def _contact_type(heading: str) -> Optional[str]:
        if "profile" in heading:
            return "linkedin"
        if "website" in heading:
            return "website"
        if "email" in heading:
            return "email"
        if "phone" in heading:
            return "phone"
        if "twitter" in heading or "x.com" in heading:
            return "twitter"
        if "birthday" in heading:
            return "birthday"
        if "address" in heading:
            return "address"
        return None


# ═══════════════════════════════════════════════════════════════════
#  PeopleSearchScraper
# ═══════════════════════════════════════════════════════════════════

class PeopleSearchScraper:
    """
    Scraper for LinkedIn people search results pages.

    Navigates to ``/search/results/people/`` and extracts name,
    headline, location, and profile URL from rendered cards.

    Example::

        async with BrowserManager(headless=False) as browser:
            await browser.load_session("linkedin_session.json")
            scraper = PeopleSearchScraper(browser.page)
            response = await scraper.search(
                keywords="python developer",
                location="Минск",
                max_pages=3,
            )
            for person in response.results:
                print(person.name, person.location, person.linkedin_url)
    """

    BASE_URL = "https://www.linkedin.com/search/results/people/"

    def __init__(self, page: Page):
        self.page = page

    # ── public API ───────────────────────────────────────────────

    async def search(
        self,
        keywords: str,
        location: Optional[str] = None,
        max_pages: int = 1,
    ) -> PeopleSearchResponse:
        """
        Search for people on LinkedIn via the browser.

        Args:
            keywords: Search query (position title, skills, etc.).
            location: Optional location appended to keywords.
            max_pages: Maximum result pages to scrape (10 results/page).

        Returns:
            PeopleSearchResponse with de-duplicated results.
        """
        if max_pages < 1:
            max_pages = 1

        combined = f"{keywords} {location}" if location else keywords
        logger.info("People search: keywords=%r, location=%r, max_pages=%d", keywords, location, max_pages)

        all_results: List[PeopleSearchResult] = []
        pages_scraped = 0

        for page_num in range(1, max_pages + 1):
            url = self._build_url(combined, page_num)
            logger.info("Scraping page %d: %s", page_num, url)

            await self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await _detect_rate_limit(self.page)

            # Wait for login check
            start = time.time()
            while time.time() - start < 10:
                if await is_logged_in(self.page):
                    break
                await asyncio.sleep(0.5)

            try:
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            await asyncio.sleep(2)

            page_results = await self._extract_results()
            pages_scraped += 1

            if not page_results:
                logger.info("No results on page %d — stopping.", page_num)
                break

            all_results.extend(page_results)

            if page_num < max_pages and not await self._has_next_page():
                logger.info("No more pages — stopping.")
                break

        # De-duplicate by URL
        seen: set[str] = set()
        unique: List[PeopleSearchResult] = []
        for r in all_results:
            if r.linkedin_url not in seen:
                seen.add(r.linkedin_url)
                unique.append(r)

        logger.info("People search complete: %d unique results, %d pages", len(unique), pages_scraped)

        return PeopleSearchResponse(
            query_keywords=keywords,
            query_location=location,
            results=unique,
            total_pages_scraped=pages_scraped,
        )

    # ── internals ────────────────────────────────────────────────

    @staticmethod
    def _build_url(keywords: str, page: int = 1) -> str:
        params: dict[str, str] = {
            "keywords": keywords,
            "origin": "GLOBAL_SEARCH_HEADER",
        }
        if page > 1:
            params["page"] = str(page)
        return f"{PeopleSearchScraper.BASE_URL}?{urlencode(params)}"

    async def _extract_results(self) -> List[PeopleSearchResult]:
        """Extract people cards from the current search results page.

        LinkedIn SDUI (2025+): each result card is an ``<a href="/in/...">``
        with ``<p>`` children for name, headline, location.
        """
        results: List[PeopleSearchResult] = []
        try:
            raw = await self.page.evaluate("""() => {
                const out = [];
                const seen = new Set();

                const nameMap = new Map();
                document.querySelectorAll('main a[href*="/in/"]').forEach(a => {
                    if (a.parentElement?.tagName === 'P') {
                        const href = a.getAttribute('href');
                        if (href) nameMap.set(href, a.textContent?.trim() || '');
                    }
                });

                document.querySelectorAll('main a[href*="/in/"]').forEach(a => {
                    const href = a.getAttribute('href');
                    if (!href || seen.has(href)) return;
                    const ps = a.querySelectorAll('p');
                    if (ps.length < 2) return;
                    seen.add(href);

                    const name = nameMap.get(href) || ps[0]?.textContent?.trim() || '';
                    const headline = ps[1]?.textContent?.trim() || '';
                    const location = ps[2]?.textContent?.trim() || '';
                    out.push({ name, headline, location, url: href });
                });
                return out;
            }""")

            for item in raw:
                url = item.get("url", "")
                name = item.get("name", "").strip()
                headline = item.get("headline", "").strip()
                loc = item.get("location", "").strip()

                if not name or not url:
                    continue
                if not url.startswith("http"):
                    url = f"https://www.linkedin.com{url}"
                url = url.split("?")[0]

                results.append(PeopleSearchResult(
                    name=name,
                    headline=headline or None,
                    location=loc or None,
                    linkedin_url=url,
                ))
        except Exception as e:
            logger.warning("Error extracting search results: %s", e)
        return results

    async def _has_next_page(self) -> bool:
        try:
            btn = self.page.locator('[data-testid="pagination-controls-next-button-visible"]')
            return await btn.count() > 0
        except Exception:
            return False
