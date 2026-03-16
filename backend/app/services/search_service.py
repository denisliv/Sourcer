"""Search orchestration: run HH/LinkedIn searches, persist candidates, AI evaluation stream."""

import asyncio
import json
import logging
import uuid as _uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import HH_AREA_HOST_MAP
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.candidate import Candidate as CandidateModel
from app.models.credential import Credential
from app.models.search import Search as SearchModel
from app.models.user import User
from app.services.evaluation_service import evaluate_candidate, prepare_candidate_context
from app.services.hh_service import MAX_TOTAL, fetch_full_resume, get_hh_headers, run_hh_search
from app.services.linkedin_service import search_linkedin

logger = logging.getLogger(__name__)

HH_RESUME_API_URL = "https://api.hh.ru/resumes"


def normalize_sources(s: str) -> tuple[bool, bool]:
    """Parse sources: 'hh' | 'linkedin' | 'both' -> (use_hh, use_linkedin)."""
    s = (s or "both").lower().strip()
    if s == "hh":
        return True, False
    if s == "linkedin":
        return False, True
    return True, True


async def get_linkedin_credential(user: User, db: AsyncSession) -> Credential | None:
    result = await db.execute(
        select(Credential).where(
            Credential.user_id == user.id,
            Credential.provider == "linkedin",
            Credential.status.in_(["active", "expired"]),
        )
    )
    return result.scalar_one_or_none()


async def execute_search(
    *,
    user: User,
    db: AsyncSession,
    search_record: SearchModel,
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
    use_hh: bool,
    use_linkedin: bool,
) -> dict:
    """Run search across HH/LinkedIn, persist candidates, return response dict."""
    count = max(1, min(count, MAX_TOTAL))

    hh_candidates: list[dict] = []
    li_candidates: list[dict] = []
    hh_total_found = 0
    hh_error: str | None = None
    li_error: str | None = None

    async def _run_hh() -> tuple[list[dict], int, str | None]:
        headers = await get_hh_headers(user, db)
        if headers is None:
            return [], 0, "HH credentials не настроены. Перейдите в Личный кабинет."
        try:
            cand, total = await run_hh_search(
                headers=headers,
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
                count=count,
            )
            return cand, total, None
        except Exception as e:
            return [], 0, str(e)

    li_cred_ref: Credential | None = None

    async def _run_li() -> tuple[list[dict], str | None, dict | None]:
        nonlocal li_cred_ref
        li_cred = await get_linkedin_credential(user, db)
        li_cred_ref = li_cred
        if li_cred is None:
            return [], "LinkedIn credentials не настроены. Перейдите в Личный кабинет.", None
        try:
            cand, cookies_to_persist = await search_linkedin(
                cred_encrypted=li_cred.encrypted_data,
                search_text=search_text,
                search_skills=search_skills,
                area=area,
                count=count,
            )
            return cand, None, cookies_to_persist
        except ValueError as e:
            return [], str(e), None
        except Exception as e:
            return [], str(e)[:300], None

    li_cookies = None
    if use_hh and use_linkedin:
        (hh_candidates, hh_total_found, hh_error), (li_candidates, li_error, li_cookies) = (
            await asyncio.gather(_run_hh(), _run_li())
        )
    elif use_hh:
        hh_candidates, hh_total_found, hh_error = await _run_hh()
    else:
        li_candidates, li_error, li_cookies = await _run_li()

    if li_cookies and li_cred_ref:
        try:
            cred_data = decrypt_credentials(li_cred_ref.encrypted_data)
            cred_data["cookies"] = li_cookies
            li_cred_ref.encrypted_data = encrypt_credentials(cred_data)
            li_cred_ref.status = "active"
            await db.flush()
        except Exception:
            pass

    candidates = hh_candidates + li_candidates

    _save_hh_candidates(db, search_record.id, hh_candidates)
    _save_li_candidates(db, search_record.id, li_candidates, offset=len(hh_candidates))

    has_error = (use_hh and hh_error) or (use_linkedin and li_error)
    if has_error and not candidates:
        search_record.status = "failed"
        msgs = [m for m in [hh_error, li_error] if m]
        search_record.error_message = "; ".join(msgs)[:500]
    else:
        search_record.status = "done"
        if has_error:
            search_record.error_message = "; ".join(m for m in [hh_error, li_error] if m)[:500]

    search_record.total_results = len(candidates)
    search_record.completed_at = datetime.now(timezone.utc)
    await db.flush()

    if not candidates and has_error:
        return {"error": True, "message": "; ".join(m for m in [hh_error, li_error] if m)}

    total_found_val = hh_total_found if (use_hh and not use_linkedin) else (
        hh_total_found + len(li_candidates) if use_hh else len(li_candidates)
    )
    return {
        "error": False,
        "search_id": str(search_record.id),
        "total_found": total_found_val,
        "returned": len(candidates),
        "candidates": candidates,
    }


def _save_hh_candidates(
    db: AsyncSession,
    search_id: _uuid.UUID,
    candidates: list[dict],
    offset: int = 0,
) -> None:
    for i, c in enumerate(candidates):
        db.add(CandidateModel(
            search_id=search_id,
            source="hh",
            external_id=c.get("external_id", ""),
            full_name=c["full_name"],
            current_title=c["title"],
            location=c["area"],
            profile_url=c["url"],
            position=offset + i,
            photo=c.get("photo"),
            experience=c.get("experience"),
            last_work=c.get("last_work"),
            salary=c.get("salary"),
            resume_updated_at=c.get("updated_at"),
        ))


def _save_li_candidates(
    db: AsyncSession,
    search_id: _uuid.UUID,
    candidates: list[dict],
    offset: int = 0,
) -> None:
    for i, c in enumerate(candidates):
        ext_id = c.get("urn_id") or ""
        if not ext_id and c.get("url"):
            ext_id = c["url"].split("/in/")[-1].rstrip("/").split("?")[0] or ""
        c.setdefault("source", "linkedin")
        c["external_id"] = ext_id
        db.add(CandidateModel(
            search_id=search_id,
            source="linkedin",
            external_id=ext_id,
            full_name=c["full_name"],
            current_title=c["title"],
            location=c["area"],
            profile_url=c["url"],
            position=offset + i,
            photo=c.get("photo"),
            experience=c.get("experience"),
            last_work=c.get("last_work"),
            salary=c.get("salary"),
            resume_updated_at=c.get("updated_at"),
        ))


async def build_evaluation_stream(
    *,
    db: AsyncSession,
    user: User,
    hh_candidates: list[CandidateModel],
    job_description: str,
    reset: bool,
    area: int = 16,
) -> AsyncGenerator[str, None]:
    """Yield SSE events for AI evaluation of candidates."""
    headers = await get_hh_headers(user, db)
    if headers is None:
        yield _sse({"status": "error", "summary": "HH credentials не настроены."})
        return

    if reset:
        for c in hh_candidates:
            c.ai_score = None
            c.ai_summary = None
            c.ai_status = None
        await db.commit()

    to_evaluate = hh_candidates if reset else [c for c in hh_candidates if c.ai_status != "done"]
    total = len(hh_candidates)
    already_done = total - len(to_evaluate)
    evaluated = already_done
    errors = 0

    for idx, candidate in enumerate(to_evaluate):
        global_idx = already_done + idx + 1
        ext_id = candidate.external_id or str(candidate.id)

        yield _sse({"status": "processing", "external_id": ext_id, "index": global_idx, "total": total})

        candidate.ai_status = "processing"
        await db.commit()

        resume_data = None
        if candidate.raw_data:
            resume_data = candidate.raw_data
        else:
            resume_host = HH_AREA_HOST_MAP.get(area, "rabota.by")
            resume_url = f"{HH_RESUME_API_URL}/{ext_id}?host={resume_host}"
            try:
                body = await fetch_full_resume(headers, resume_url)
                resume_data = json.loads(body)
                candidate.raw_data = resume_data
                await db.commit()
            except Exception as e:
                logger.warning("Failed to fetch resume %s: %s", ext_id, e)
                candidate.ai_status = "error"
                candidate.ai_summary = f"Ошибка загрузки резюме: {str(e)[:200]}"
                await db.commit()
                errors += 1
                yield _sse({"status": "error", "external_id": ext_id, "summary": candidate.ai_summary})
                continue

        context = prepare_candidate_context(resume_data)
        eval_result = await evaluate_candidate(job_description, context)

        candidate.ai_score = eval_result["score"]
        candidate.ai_summary = eval_result["summary"]
        candidate.ai_status = "done" if eval_result["score"] is not None else "error"
        await db.commit()

        if eval_result["score"] is not None:
            evaluated += 1
            yield _sse({
                "status": "done",
                "external_id": ext_id,
                "score": eval_result["score"],
                "summary": eval_result["summary"],
            })
        else:
            errors += 1
            yield _sse({
                "status": "error",
                "external_id": ext_id,
                "summary": eval_result["summary"],
            })

        await asyncio.sleep(0.3)

    yield _sse({"status": "complete", "evaluated": evaluated, "errors": errors, "total": total})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
