"""AI candidate evaluation service.

Fetches full resume JSON from HH API, extracts relevant fields,
builds a text context, and sends it to LLM for scoring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from openai import AsyncOpenAI

from app.core.config import (
    EVALUATION_SYSTEM_PROMPT,
    EVALUATION_TEMPERATURE,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None
_llm_semaphore: asyncio.Semaphore | None = None


def init_semaphore(max_concurrent: int) -> None:
    global _llm_semaphore
    _llm_semaphore = asyncio.Semaphore(max_concurrent)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)
    return _client


# ── helpers ───────────────────────────────────────────────────────

_MONTH_NAMES = [
    "", "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def _format_date(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        parts = date_str.split("-")
        year = parts[0]
        month_idx = int(parts[1]) if len(parts) > 1 else 0
        month = _MONTH_NAMES[month_idx] if 1 <= month_idx <= 12 else ""
        return f"{month} {year}" if month else year
    except (ValueError, IndexError):
        return date_str


def _format_experience_months(months: int | None) -> str:
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


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ── context preparation ──────────────────────────────────────────

def prepare_candidate_context(data: dict) -> str:
    """Extract relevant fields from full HH resume JSON and format as text for LLM.

    Excludes: area, salary, photo, URLs, IDs, and all service fields.
    """
    lines: list[str] = []

    title = data.get("title") or "—"
    lines.append(f"Резюме: {title}")

    age = data.get("age")
    if age:
        lines.append(f"Возраст: {age}")

    total_exp = data.get("total_experience")
    if total_exp and total_exp.get("months") is not None:
        lines.append(f"Общий опыт: {_format_experience_months(total_exp['months'])}")

    # About me
    skills_text = data.get("skills")
    if skills_text:
        cleaned = _strip_html(skills_text)
        if cleaned:
            lines.append(f"\nОбо мне:\n{cleaned}")

    # Work experience
    experience = data.get("experience") or []
    if experience:
        lines.append("\nОпыт работы:")
        for exp in experience:
            company = exp.get("company") or "—"
            position = exp.get("position") or "—"
            start = _format_date(exp.get("start"))
            end = _format_date(exp.get("end")) or "наст. время"
            period = f"({start} — {end})" if start else ""

            industries = exp.get("industries") or []
            industry_names = [i.get("name", "") for i in industries if i.get("name")]
            industry_str = f" [{', '.join(industry_names)}]" if industry_names else ""

            lines.append(f"- {company} / {position} {period}{industry_str}")

            description = exp.get("description")
            if description:
                cleaned_desc = _strip_html(description)
                if cleaned_desc:
                    for desc_line in cleaned_desc.split("\n"):
                        desc_line = desc_line.strip()
                        if desc_line:
                            lines.append(f"  {desc_line}")

    # Key skills
    skill_set = data.get("skill_set") or []
    if skill_set:
        lines.append(f"\nКлючевые навыки: {', '.join(skill_set)}")

    # Education
    education = data.get("education")
    if education:
        level = education.get("level", {}).get("name", "")
        if level:
            lines.append(f"\nОбразование: {level}")
        primary = education.get("primary") or []
        for edu in primary:
            parts = [p for p in [
                edu.get("name"),
                edu.get("organization"),
                edu.get("result"),
                str(edu.get("year")) if edu.get("year") else None,
            ] if p]
            if parts:
                lines.append(f"- {', '.join(parts)}")

    # Certificates
    certificates = data.get("certificate") or []
    if certificates:
        lines.append("\nСертификаты:")
        for cert in certificates:
            cert_title = cert.get("title") or "—"
            achieved = cert.get("achieved_at", "")
            year = achieved[:4] if achieved else ""
            lines.append(f"- {cert_title}" + (f" ({year})" if year else ""))

    # Languages
    languages = data.get("language") or []
    if languages:
        lang_parts = []
        for lang in languages:
            name = lang.get("name", "")
            level = lang.get("level", {}).get("name", "")
            lang_parts.append(f"{name} ({level})" if level else name)
        if lang_parts:
            lines.append(f"\nЯзыки: {', '.join(lang_parts)}")

    # Citizenship
    citizenships = data.get("citizenship") or []
    cit_names = [c.get("name", "") for c in citizenships if c.get("name")]
    if cit_names:
        lines.append(f"\nГражданство: {', '.join(cit_names)}")

    return "\n".join(lines)


# ── LLM evaluation ──────────────────────────────────────────────

async def evaluate_candidate(job_description: str, candidate_context: str) -> dict:
    """Send candidate context + job description to LLM, return score and summary.

    Always returns {"score": int|None, "summary": str}.
    """
    sem = _llm_semaphore
    if sem is None:
        raise RuntimeError("Semaphore not initialised — call init_semaphore() first")

    user_message = (
        f"=== ОПИСАНИЕ ВАКАНСИИ ===\n{job_description}\n\n"
        f"=== ИНФОРМАЦИЯ О КАНДИДАТЕ ===\n{candidate_context}"
    )

    async with sem:
        client = _get_client()
        try:
            resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=EVALUATION_TEMPERATURE,
                max_tokens=300,
            )
        except Exception:
            logger.exception("LLM API call failed")
            return {"score": None, "summary": "Ошибка вызова LLM"}

    response_text = (resp.choices[0].message.content or "").strip()

    try:
        result = json.loads(response_text)
        score = int(result["score"])
        if not 1 <= score <= 10:
            raise ValueError(f"score {score} out of range")
        summary = str(result.get("summary", ""))
        return {"score": score, "summary": summary}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse LLM response: %s | raw: %s", exc, response_text[:200])
        return {"score": None, "summary": "Ошибка анализа"}
