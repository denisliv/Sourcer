"""
Main LinkedIn API class.

Provides search_people() and get_profile() via LinkedIn's Voyager
(GraphQL) API using cookies-based authentication.

Usage with pre-saved session cookies:

    from linkedin_api import Linkedin
    cookies = load_cookies(...)     # RequestsCookieJar
    api = Linkedin(cookies=cookies)
    results = api.search_people(keyword_title="python developer", limit=10)
    profile = api.get_profile(public_id="johndoe")
"""

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote, urlencode

from .client import Client
from .exceptions import LinkedInRequestError, UnauthorizedError

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────

def _get_id_from_urn(urn: str) -> str:
    if not urn or ":" not in urn:
        return ""
    parts = urn.split(":")
    return parts[3] if len(parts) > 3 else ""


def _get_urn_from_raw(raw: str) -> str:
    return raw.split("(")[1].split(",")[0]


def _extract_profile_section(
    profile: Dict, view_key: str, profile_key: str,
    nested_group_key: Optional[str] = None,
) -> List[Dict]:
    """Extract section from denormalized LinkedIn profile data."""
    result = []

    view = profile.get(view_key, {})
    if isinstance(view, dict):
        elements = view.get("elements")
        if elements:
            return elements

    prof = profile.get(profile_key, {})
    if isinstance(prof, dict):
        elements = prof.get("*elements")
        if elements:
            if nested_group_key:
                for group in elements:
                    if isinstance(group, dict):
                        nested = group.get(nested_group_key, {})
                        if isinstance(nested, dict):
                            result.extend(nested.get("*elements", []))
                return result
            return elements

    return result


# ═══════════════════════════════════════════════════════════════════
#  Linkedin class
# ═══════════════════════════════════════════════════════════════════

class Linkedin:
    """High-level interface to LinkedIn Voyager API."""

    _MAX_SEARCH_COUNT = 49
    _MAX_REPEATED_REQUESTS = 200

    # Search queryId — LinkedIn rotates these when they update GraphQL.
    _SEARCH_QUERY_IDS = [
        "voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0",  # Feb 2026
        "voyagerSearchDashClusters.5e03c5de2fddefb3fa19f8b35e1c0c49",  # pre-2026
    ]
    _active_search_query_id: str = _SEARCH_QUERY_IDS[0]

    # Mapping from result section → $type substrings in 'included'
    _SECTION_TYPE_MAP = {
        "experience": [".profile.Position"],
        "education": [".profile.Education"],
        "skills": [".profile.Skill"],
        "languages": [".profile.Language"],
        "certifications": [".profile.Certification"],
        "publications": [".profile.Publication"],
        "volunteer": [".profile.VolunteerExperience"],
        "honors": [".profile.Honor"],
        "projects": [".profile.Project"],
    }

    def __init__(
        self,
        username: str = "",
        password: str = "",
        *,
        cookies=None,
        authenticate: bool = True,
        debug: bool = False,
        proxies: dict | None = None,
    ):
        """
        Create a Linkedin API instance.

        For cookie-based auth (recommended):
            Linkedin(cookies=jar)

        For username/password auth:
            Linkedin("user@mail.com", "password")
        """
        self.client = Client(debug=debug, proxies=proxies)
        logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

        if authenticate:
            if cookies:
                self.client.set_cookies(cookies)
            elif username and password:
                self.client.authenticate(username, password)

    # ── HTTP helpers ─────────────────────────────────────────────

    def _fetch(self, uri: str, **kwargs):
        self.client.rate_limiter.wait()
        url = f"{self.client.API_BASE_URL}{uri}"
        res = self.client.session.get(url, **kwargs)
        if res.status_code == 401:
            raise UnauthorizedError()
        if not 200 <= res.status_code < 300:
            raise LinkedInRequestError(res.status_code, res.text[:500])
        return res

    def _post(self, uri: str, **kwargs):
        self.client.rate_limiter.wait()
        url = f"{self.client.API_BASE_URL}{uri}"
        res = self.client.session.post(url, **kwargs)
        if res.status_code == 401:
            raise UnauthorizedError()
        if not 200 <= res.status_code < 300:
            raise LinkedInRequestError(res.status_code, res.text[:500])
        return res

    # ═════════════════════════════════════════════════════════════
    #  SEARCH
    # ═════════════════════════════════════════════════════════════

    def search_people(
        self,
        keywords: Optional[str] = None,
        connection_of: Optional[str] = None,
        network_depths: Optional[List[Union[Literal["F"], Literal["S"], Literal["O"]]]] = None,
        current_company: Optional[List[str]] = None,
        past_companies: Optional[List[str]] = None,
        nonprofit_interests: Optional[List[str]] = None,
        profile_languages: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        industries: Optional[List[str]] = None,
        schools: Optional[List[str]] = None,
        contact_interests: Optional[List[str]] = None,
        service_categories: Optional[List[str]] = None,
        include_private_profiles: bool = False,
        keyword_first_name: Optional[str] = None,
        keyword_last_name: Optional[str] = None,
        keyword_title: Optional[str] = None,
        keyword_company: Optional[str] = None,
        keyword_school: Optional[str] = None,
        network_depth: Optional[Union[Literal["F"], Literal["S"], Literal["O"]]] = None,
        title: Optional[str] = None,
        **kwargs,
    ) -> List[Dict]:
        """Search for people on LinkedIn.

        Returns a list of dicts with keys:
            urn_id, distance, jobtitle, location, name, navigation_url

        All filter parameters are optional. Commonly used:
            keyword_title   — filter by current job title
            keywords        — full-text search across profile
            regions         — list of Geo URN IDs
            include_private_profiles — include OUT_OF_NETWORK members
            limit           — max results (pass via kwargs)
        """
        filters = ["(key:resultType,value:List(PEOPLE))"]

        if connection_of:
            filters.append(f"(key:connectionOf,value:List({connection_of}))")
        if network_depths:
            filters.append(f"(key:network,value:List({' | '.join(network_depths)}))")
        elif network_depth:
            filters.append(f"(key:network,value:List({network_depth}))")
        if regions:
            filters.append(f"(key:geo,value:List({' | '.join(regions)}))")
        if industries:
            filters.append(f"(key:industry,value:List({' | '.join(industries)}))")
        if current_company:
            filters.append(f"(key:currentCompany,value:List({' | '.join(current_company)}))")
        if past_companies:
            filters.append(f"(key:pastCompany,value:List({' | '.join(past_companies)}))")
        if profile_languages:
            filters.append(f"(key:profileLanguage,value:List({' | '.join(profile_languages)}))")
        if nonprofit_interests:
            filters.append(f"(key:nonprofitInterest,value:List({' | '.join(nonprofit_interests)}))")
        if schools:
            filters.append(f"(key:schools,value:List({' | '.join(schools)}))")
        if service_categories:
            filters.append(f"(key:serviceCategory,value:List({' | '.join(service_categories)}))")

        keyword_title = keyword_title or title
        if keyword_first_name:
            filters.append(f"(key:firstName,value:List({keyword_first_name}))")
        if keyword_last_name:
            filters.append(f"(key:lastName,value:List({keyword_last_name}))")
        if keyword_title:
            filters.append(f"(key:title,value:List({keyword_title}))")
        if keyword_company:
            filters.append(f"(key:company,value:List({keyword_company}))")
        if keyword_school:
            filters.append(f"(key:school,value:List({keyword_school}))")

        params = {"filters": "List({})".format(",".join(filters))}
        if keywords:
            params["keywords"] = keywords

        data = self._search(params, **kwargs)

        results = []
        for item in data:
            if (
                not include_private_profiles
                and (item.get("entityCustomTrackingInfo") or {}).get("memberDistance") == "OUT_OF_NETWORK"
            ):
                continue
            urn_id = _get_id_from_urn(
                _get_urn_from_raw(item.get("entityUrn", "()"))
            )
            nav_url = item.get("navigationUrl")
            if nav_url and "/headless" in nav_url:
                nav_url = None
            results.append({
                "urn_id": urn_id,
                "distance": (item.get("entityCustomTrackingInfo") or {}).get("memberDistance"),
                "jobtitle": (item.get("primarySubtitle") or {}).get("text"),
                "location": (item.get("secondarySubtitle") or {}).get("text"),
                "name": (item.get("title") or {}).get("text"),
                "navigation_url": nav_url,
            })
        return results

    # ── generic search engine ────────────────────────────────────

    def _search(self, params: Dict, limit: int = -1, offset: int = 0) -> List:
        count = self._MAX_SEARCH_COUNT
        if limit is None:
            limit = -1

        results: list = []
        while True:
            if limit > -1 and limit - len(results) < count:
                count = limit - len(results)
            default = {
                "count": str(count),
                "filters": "List()",
                "origin": "GLOBAL_SEARCH_HEADER",
                "q": "all",
                "start": len(results) + offset,
                "queryContext": "List(spellCorrectionEnabled->true,relatedSearchesEnabled->true,kcardTypes->PROFILE|COMPANY)",
                "includeWebMetadata": "true",
            }
            default.update(params)

            kw = f"keywords:{default['keywords']}," if "keywords" in default else ""

            variables = (
                f"(start:{default['start']},origin:{default['origin']},"
                f"query:({kw}flagshipSearchIntent:SEARCH_SRP,"
                f"queryParameters:{default['filters']},"
                f"includeFiltersInResponse:false))"
            )

            data = self._fetch_search_with_fallback(variables)

            outer = data.get("data", {})
            clusters = outer.get("searchDashClustersByAll") or outer.get("data", {}).get("searchDashClustersByAll", {})
            if not clusters:
                return results

            included_map: dict = {}
            for inc in data.get("included", []):
                urn = inc.get("entityUrn")
                if urn:
                    included_map[urn] = inc

            new_elements: list = []
            for it in clusters.get("elements", []):
                etype = it.get("_type") or it.get("$type", "")
                if "SearchClusterViewModel" not in etype and etype:
                    continue
                for el in it.get("items", []):
                    item = el.get("item", {})
                    e = item.get("entityResult")
                    if not e:
                        ref = item.get("*entityResult", "")
                        if ref:
                            e = included_map.get(ref)
                    if not e:
                        continue
                    et = e.get("_type") or e.get("$type", "")
                    if "EntityResultViewModel" not in et:
                        continue
                    new_elements.append(e)

            results.extend(new_elements)

            if (
                (-1 < limit <= len(results))
                or len(results) / count >= self._MAX_REPEATED_REQUESTS
                or len(new_elements) == 0
            ):
                break
            logger.debug("Search results: %d so far", len(results))

        return results

    def _fetch_search_with_fallback(self, variables: str) -> dict:
        """Try active queryId first, then rotate through fallbacks."""
        try:
            uri = f"/graphql?variables={variables}&queryId={self._active_search_query_id}"
            return self._fetch(uri).json()
        except LinkedInRequestError as e:
            if e.status_code != 500:
                raise
            logger.warning("queryId %s returned 500 — trying fallbacks", self._active_search_query_id)

        for qid in self._SEARCH_QUERY_IDS:
            if qid == self._active_search_query_id:
                continue
            try:
                uri = f"/graphql?variables={variables}&queryId={qid}"
                data = self._fetch(uri).json()
                logger.info("Search queryId rotated to %s", qid)
                Linkedin._active_search_query_id = qid
                return data
            except LinkedInRequestError as e:
                if e.status_code != 500:
                    raise
                continue

        raise LinkedInRequestError(
            500,
            "All known search queryIds returned 500. "
            "LinkedIn likely rotated their GraphQL schema — manual update required.",
        )

    # ═════════════════════════════════════════════════════════════
    #  PROFILE
    # ═════════════════════════════════════════════════════════════

    def get_profile(
        self, public_id: Optional[str] = None, urn_id: Optional[str] = None,
    ) -> Dict:
        """Fetch a LinkedIn profile via Voyager API.

        Returns a dict with keys: public_id, firstName, lastName, headline,
        summary, location, profilePictureUrl, profileUrl, experience,
        education, skills, languages, certifications, etc.
        """
        if public_id and not urn_id:
            urn_id = self._extract_urn_from_public_id(public_id)
            if not urn_id:
                return {}
        if not urn_id:
            logger.error("Either public_id or urn_id must be provided")
            return {}

        urn_id = self._normalize_urn(urn_id)
        profile = self._fetch_profile_from_dash_api(urn_id)
        if not profile:
            return {}

        included = profile.pop("_included", [])

        # Location
        location_name = profile.get("locationName")
        geo_location_name = profile.get("geoLocationName")
        if not location_name or not geo_location_name:
            geo_loc = profile.get("geoLocation") or profile.get("*geoLocation", {})
            if isinstance(geo_loc, dict):
                geo = geo_loc.get("geo") or geo_loc.get("*geo", {})
                if isinstance(geo, dict):
                    if not geo_location_name:
                        geo_location_name = geo.get("defaultLocalizedName")
                    if not location_name:
                        location_name = (
                            geo.get("defaultLocalizedNameWithoutCountryName")
                            or geo.get("defaultLocalizedName")
                        )

        # Profile picture
        pic_url = None
        pic = profile.get("profilePicture", {})
        vi = pic.get("displayImageReference", {}).get("vectorImage", {}) if isinstance(pic, dict) else {}
        if isinstance(vi, dict):
            root = vi.get("rootUrl", "")
            artifacts = vi.get("artifacts", [])
            if artifacts and root:
                best = max(artifacts, key=lambda a: a.get("width", 0))
                seg = best.get("fileIdentifyingUrlPathSegment", "")
                if seg:
                    pic_url = f"{root}{seg}"

        result: Dict[str, Any] = {
            "public_id": profile.get("publicIdentifier"),
            "firstName": profile.get("firstName"),
            "lastName": profile.get("lastName"),
            "headline": profile.get("headline"),
            "summary": (
                profile.get("multiLocaleSummary", {}).get("en_US")
                if isinstance(profile.get("multiLocaleSummary"), dict)
                else profile.get("summary")
            ),
            "location": geo_location_name or location_name,
            "profilePictureUrl": pic_url,
            "profileUrl": (
                f"https://www.linkedin.com/in/{profile.get('publicIdentifier')}/"
                if profile.get("publicIdentifier") else None
            ),
        }

        # Sections from denormalized data
        result["experience"] = _extract_profile_section(
            profile, "*positionView", "profilePositionGroups", "profilePositionInPositionGroup",
        )
        result["education"] = _extract_profile_section(profile, "*educationView", "profileEducations")
        result["languages"] = _extract_profile_section(profile, "*languageView", "profileLanguages")
        result["skills"] = _extract_profile_section(profile, "*skillView", "profileSkills")
        result["certifications"] = _extract_profile_section(profile, "*certificationView", "profileCertifications")
        result["publications"] = _extract_profile_section(profile, "*publicationView", "profilePublications")
        result["volunteer"] = _extract_profile_section(profile, "*volunteerExperienceView", "profileVolunteerExperiences")
        result["honors"] = _extract_profile_section(profile, "*honorView", "profileHonors")
        result["projects"] = _extract_profile_section(profile, "*projectView", "profileProjects")

        # From included entities
        if included:
            self._extract_sections_from_included(result, included)

        self._clean_sections(result)
        result["urn_id"] = urn_id.replace("urn:li:fsd_profile:", "")
        return result

    # ── profile internals ────────────────────────────────────────

    def _normalize_urn(self, urn_id: str) -> str:
        if not urn_id.startswith("urn:"):
            return f"urn:li:fsd_profile:{urn_id}"
        return urn_id

    def _fetch_profile_from_dash_api(self, urn_id: str) -> Optional[Dict]:
        decorations = [
            "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93",
            "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-105",
            "com.linkedin.voyager.dash.deco.identity.profile.FullProfile-76",
        ]
        for dec in decorations:
            try:
                res = self._fetch(f"/identity/dash/profiles/{urn_id}?{urlencode({'decorationId': dec})}")
                raw = res.json()
                if not raw:
                    continue
                profile = self._denormalize(raw)
                if not profile:
                    return None
                profile["_included"] = raw.get("included", [])
                return profile
            except Exception as e:
                logger.debug("Decoration %s failed: %s", dec, e)
                continue
        logger.error("All dash API decorations failed for %s", urn_id)
        return None

    def _extract_urn_from_public_id(self, public_id: str) -> Optional[str]:
        # GraphQL
        try:
            qid = "voyagerIdentityDashProfiles.a1a483e719b20537a256b6853cdca711"
            variables = f"(vanityName:{public_id})"
            qs = urlencode({"includeWebMetadata": "true", "variables": variables, "queryId": qid})
            res = self._fetch(f"/graphql?{qs}")
            data = res.json()
            elements = (
                data.get("data", {}).get("data", {})
                .get("identityDashProfilesByMemberIdentity", {})
                .get("*elements", [])
            )
            if elements and "fsd_profile" in str(elements[0]):
                return elements[0]
        except Exception as e:
            logger.warning("GraphQL URN extraction failed: %s", e)

        # HTML fallback
        try:
            from bs4 import BeautifulSoup
            encoded = quote(public_id, safe="")
            r = self.client.session.get(f"{self.client.LINKEDIN_BASE_URL}/in/{encoded}/")
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            # JSON-LD
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    d = json.loads(script.string)
                    if isinstance(d, dict) and d.get("@type") == "Person":
                        ident = d.get("identifier")
                        if ident and "fsd_profile" in str(ident):
                            return ident if ident.startswith("urn:") else f"urn:li:fsd_profile:{ident}"
                except Exception:
                    continue
            # Regex
            pattern = r"urn:li:fsd_profile:[A-Za-z0-9_-]{8,}"
            for tag in soup.find_all(["code", "script"]):
                if tag.string and "fsd_profile" in tag.string:
                    m = re.search(pattern, tag.string)
                    if m:
                        return m.group(0)
        except Exception as e:
            logger.error("HTML URN extraction failed: %s", e)
        return None

    # ── response denormalization ─────────────────────────────────

    def _denormalize(self, raw: Dict) -> Dict:
        data = raw.get("data", raw)
        included = raw.get("included", [])
        if not included:
            return data
        lookup = {item["entityUrn"]: item for item in included if "entityUrn" in item}
        return self._resolve(data, lookup, False)

    def _resolve(self, obj: Any, lookup: Dict, is_ref: bool) -> Any:
        if isinstance(obj, str):
            if is_ref and obj in lookup:
                return self._resolve(lookup[obj], lookup, False)
            return obj
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                kr = k.startswith("*")
                rv = self._resolve(v, lookup, kr)
                out[k] = rv
                if kr:
                    bare = k[1:]
                    if bare not in obj:
                        out[bare] = rv
            return out
        if isinstance(obj, list):
            return [self._resolve(i, lookup, is_ref) for i in obj]
        return obj

    # ── section extraction from included ─────────────────────────

    def _extract_sections_from_included(self, result: Dict, included: List[Dict]) -> None:
        for key, patterns in self._SECTION_TYPE_MAP.items():
            if result.get(key):
                continue
            entities = [
                e for e in included
                if any(p in e.get("$type", "") for p in patterns)
                and "Group" not in e.get("$type", "")
                and "View" not in e.get("$type", "")
            ]
            if entities:
                result[key] = entities

    # ── section cleaning ─────────────────────────────────────────

    def _clean_sections(self, result: Dict) -> None:
        if result.get("experience"):
            result["experience"] = [self._clean_exp(e) for e in result["experience"]]
        if result.get("education"):
            result["education"] = [self._clean_edu(e) for e in result["education"]]
        if result.get("skills"):
            result["skills"] = [
                e.get("name") for e in result["skills"] if isinstance(e, dict) and e.get("name")
            ]
        if result.get("languages"):
            result["languages"] = [
                {"name": e.get("name"), "proficiency": e.get("proficiency")}
                for e in result["languages"] if isinstance(e, dict) and e.get("name")
            ]
        if result.get("certifications"):
            result["certifications"] = [self._clean_cert(e) for e in result["certifications"]]
        if result.get("publications"):
            result["publications"] = [self._clean_pub(e) for e in result["publications"]]
        if result.get("volunteer"):
            result["volunteer"] = [
                {"role": e.get("role"), "companyName": e.get("companyName"), "description": e.get("description")}
                for e in result["volunteer"] if isinstance(e, dict)
            ]
        if result.get("projects"):
            result["projects"] = [
                {"title": e.get("title"), "description": e.get("description"), "url": e.get("url")}
                for e in result["projects"] if isinstance(e, dict)
            ]
        if result.get("honors"):
            result["honors"] = [
                {"title": e.get("title"), "issuer": e.get("issuer"), "description": e.get("description")}
                for e in result["honors"] if isinstance(e, dict)
            ]

    @staticmethod
    def _simplify_date(dr: Dict) -> Dict:
        out = {}
        for part in ("start", "end"):
            d = dr.get(part)
            if isinstance(d, dict):
                s = {}
                if "year" in d:
                    s["year"] = d["year"]
                if "month" in d:
                    s["month"] = d["month"]
                out[part] = s or None
            else:
                out[part] = None
        return out

    def _clean_exp(self, e: Dict) -> Dict:
        dr = e.get("dateRange", {})
        et = e.get("employmentType")
        et_name = et.get("name") if isinstance(et, dict) else (et if isinstance(et, str) else None)
        dates = self._simplify_date(dr) if dr else {"start": None, "end": None}
        return {
            "title": e.get("title"),
            "companyName": e.get("companyName"),
            "employmentType": et_name,
            "location": e.get("locationName"),
            "description": e.get("description"),
            "startDate": dates["start"],
            "endDate": dates["end"],
        }

    @staticmethod
    def _clean_edu(e: Dict) -> Dict:
        dr = e.get("dateRange", {})
        dates = Linkedin._simplify_date(dr) if dr else {"start": None, "end": None}
        return {
            "schoolName": e.get("schoolName"),
            "degreeName": e.get("degreeName"),
            "fieldOfStudy": e.get("fieldOfStudy"),
            "description": e.get("description"),
            "startDate": dates["start"],
            "endDate": dates["end"],
        }

    @staticmethod
    def _clean_cert(e: Dict) -> Dict:
        dr = e.get("dateRange", {})
        dates = Linkedin._simplify_date(dr) if dr else {"start": None, "end": None}
        return {
            "name": e.get("name"),
            "authority": e.get("authority"),
            "url": e.get("url"),
            "startDate": dates["start"],
        }

    @staticmethod
    def _clean_pub(e: Dict) -> Dict:
        pub = e.get("publishedOn", {})
        return {
            "name": e.get("name"),
            "publisher": e.get("publisher"),
            "year": pub.get("year") if isinstance(pub, dict) else None,
            "url": e.get("url"),
        }
