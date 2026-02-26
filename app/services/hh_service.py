"""HeadHunter resume search service.

Encapsulates HH API parameter building, response parsing, token management,
and paginated search execution.
"""

import asyncio
import math
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import HH_API_URL, HH_HOST
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.credential import Credential
from app.models.user import User
from app.services.hh_oauth import (
    compute_expires_at,
    is_token_expired,
    refresh_access_token,
)

MAX_PER_PAGE = 50
MAX_TOTAL = 2000


# ── parameter building ────────────────────────────────────────────

def build_params(
    search_text: str,
    search_in_positions: bool,
    search_skills: str,
    search_skills_field: str,
    search_company: str,
    exclude_title: str,
    exclude_company: str,
    experience: list[str],
    area: int,
    period: int,
    page: int,
    per_page: int,
) -> list[tuple[str, str]]:
    """Build list-of-tuples params preserving duplicate keys order.
    Each text block gets its own text.logic, text.field, text.period triad.
    """
    params: list[tuple[str, str]] = [("host", HH_HOST)]

    if search_text.strip():
        fields = ["title"]
        if search_in_positions:
            fields.append("experience_position")
        params.append(("text", search_text.strip()))
        params.append(("text.logic", "all"))
        params.append(("text.field", ",".join(fields)))
        params.append(("text.period", "all_time"))

    if search_company.strip():
        params.append(("text", search_company.strip()))
        params.append(("text.logic", "all"))
        params.append(("text.field", "experience_company"))
        params.append(("text.period", "all_time"))

    if search_skills.strip():
        skills_field = "everywhere" if search_skills_field == "everywhere" else "skills"
        skills_text = " ".join(s.strip() for s in search_skills.split(",") if s.strip())
        params.append(("text", skills_text))
        params.append(("text.logic", "all"))
        params.append(("text.field", skills_field))
        params.append(("text.period", "all_time"))

    for exp in experience:
        params.append(("experience", exp))

    if exclude_title.strip():
        params.append(("text", exclude_title.strip()))
        params.append(("text.logic", "except"))
        params.append(("text.field", "title"))
        params.append(("text.period", "all_time"))

    if exclude_company.strip():
        params.append(("text", exclude_company.strip()))
        params.append(("text.logic", "except"))
        params.append(("text.field", "experience_company"))
        params.append(("text.period", "all_time"))

    params.append(("period", str(period)))
    params.append(("area", str(area)))
    params.append(("per_page", str(per_page)))
    params.append(("page", str(page)))

    return params


# ── response parsing ──────────────────────────────────────────────

def format_experience(months: Optional[int]) -> str:
    if months is None:
        return "—"
    years = months // 12
    remaining = months % 12
    parts = []
    if years:
        parts.append(f"{years} г.")
    if remaining:
        parts.append(f"{remaining} мес.")
    return " ".join(parts) if parts else "< 1 мес."


def format_salary(salary: Optional[dict]) -> str:
    if not salary:
        return "—"
    amount = salary.get("amount")
    currency = salary.get("currency", "")
    if amount is None:
        return "—"
    currency_map = {
        "RUR": "₽", "USD": "$", "EUR": "€",
        "BYR": "BYN", "KZT": "₸", "UAH": "₴",
    }
    symbol = currency_map.get(currency, currency)
    return f"{amount:,.0f} {symbol}".replace(",", " ")


def parse_item(item: dict) -> dict:
    """Parse a single HH resume item into a flat candidate dict."""
    first = item.get("first_name") or ""
    last = item.get("last_name") or ""
    middle = item.get("middle_name") or ""
    full_name = " ".join(part for part in [last, first, middle] if part).strip()
    if not full_name:
        full_name = "—"

    photo = None
    if item.get("photo") and item["photo"].get("small"):
        photo = item["photo"]["small"]

    area_name = "—"
    if item.get("area") and item["area"].get("name"):
        area_name = item["area"]["name"]

    total_exp_months = None
    if item.get("total_experience") and item["total_experience"].get("months") is not None:
        total_exp_months = item["total_experience"]["months"]

    last_work = "—"
    exp_list = item.get("experience") or []
    if exp_list and isinstance(exp_list[0], dict):
        company = (exp_list[0].get("company") or "").strip()
        position = (exp_list[0].get("position") or "").strip()
        parts = [p for p in [company, position] if p]
        last_work = " / ".join(parts) if parts else "—"

    return {
        "source": "hh",
        "photo": photo,
        "full_name": full_name,
        "title": item.get("title", "—"),
        "area": area_name,
        "experience": format_experience(total_exp_months),
        "last_work": last_work,
        "salary": format_salary(item.get("salary")),
        "url": item.get("alternate_url", ""),
        "updated_at": item.get("updated_at", "—"),
        "fetched_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "external_id": str(item.get("id", "")),
    }


# ── credential / token helpers ────────────────────────────────────

async def get_hh_headers(user: User, db: AsyncSession) -> dict | None:
    """Load the user's HH credentials and return HTTP headers.

    If the access_token has expired, the function automatically refreshes it
    using the stored refresh_token.  When the refresh also fails the credential
    is marked ``expired`` and ``None`` is returned.
    """
    result = await db.execute(
        select(Credential).where(
            Credential.user_id == user.id,
            Credential.provider == "hh",
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None or cred.status not in ("active", "expired"):
        return None

    try:
        data = decrypt_credentials(cred.encrypted_data)
    except Exception:
        return None

    if is_token_expired(data.get("expires_at", "")):
        rt = data.get("refresh_token", "")
        if not rt:
            cred.status = "expired"
            await db.flush()
            return None
        try:
            tokens = await refresh_access_token(rt)
            data["access_token"] = tokens["access_token"]
            data["refresh_token"] = tokens.get("refresh_token", rt)
            data["expires_at"] = compute_expires_at(tokens.get("expires_in", 3600))
            cred.encrypted_data = encrypt_credentials(data)
            cred.status = "active"
            await db.flush()
        except Exception:
            cred.status = "expired"
            await db.flush()
            return None

    return {
        "HH-User-Agent": data.get("user_agent", ""),
        "Authorization": f"Bearer {data.get('access_token', '')}",
    }


# ── search execution ─────────────────────────────────────────────

async def run_hh_search(
    headers: dict,
    search_text: str,
    search_in_positions: bool,
    search_skills: str,
    search_skills_field: str,
    search_company: str,
    exclude_title: str,
    exclude_company: str,
    experience: list[str],
    area: int,
    period: int,
    count: int,
) -> tuple[list[dict], int]:
    """Run HH search, return (candidates, total_found)."""
    per_page = min(count, MAX_PER_PAGE)
    total_pages = math.ceil(count / per_page)
    candidates: list[dict] = []
    total_found = 0

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for page in range(total_pages):
            current_per_page = min(per_page, count - len(candidates))
            params = build_params(
                search_text=search_text,
                search_in_positions=search_in_positions,
                search_skills=search_skills,
                search_skills_field=search_skills_field,
                search_company=search_company,
                exclude_title=exclude_title,
                exclude_company=exclude_company,
                experience=experience,
                area=area,
                period=period,
                page=page,
                per_page=current_per_page,
            )
            resp = await client.get(HH_API_URL, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"HH API status {resp.status_code}")
            data = resp.json()
            total_found = data.get("found", 0)
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                parsed = parse_item(item)
                candidates.append(parsed)
                if len(candidates) >= count:
                    break
            if len(candidates) >= count:
                break
            await asyncio.sleep(0.25)

    return candidates, total_found
