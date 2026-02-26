"""Search and export routes: candidate search across HH and LinkedIn, CSV export."""

import asyncio
import uuid as _uuid
from datetime import datetime, timezone
from io import StringIO
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import HH_DEFAULT_AREA, HH_AREAS_DICT
from app.core.database import get_db
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.candidate import Candidate as CandidateModel
from app.models.candidate_view import CandidateView
from app.models.credential import Credential
from app.models.search import Search as SearchModel
from app.models.user import User
from app.services.audit import log_action
from app.services.hh_service import MAX_TOTAL, get_hh_headers, run_hh_search
from app.services.linkedin_service import search_linkedin

router = APIRouter(tags=["search"])


# ── helpers ───────────────────────────────────────────────────────

def _candidate_to_ui(
    c: CandidateModel,
    viewed_keys: set[tuple[str, str]] | None = None,
) -> dict:
    """Convert Candidate model to UI format."""
    extra = c.extra_data or {}
    fetched = c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else "—"
    source = c.source or "hh"
    ext_id = c.external_id or ""
    is_viewed = (source, ext_id) in viewed_keys if viewed_keys else False
    return {
        "source": source,
        "external_id": ext_id,
        "is_viewed": is_viewed,
        "photo": extra.get("photo"),
        "full_name": c.full_name or "—",
        "title": c.current_title or "—",
        "area": c.location or "—",
        "experience": extra.get("experience", "—"),
        "last_work": extra.get("last_work", "—"),
        "salary": extra.get("salary", "—"),
        "url": c.profile_url or "",
        "updated_at": extra.get("updated_at", "—"),
        "fetched_at": fetched,
    }


async def _load_viewed_keys(
    db: AsyncSession,
    user_id: _uuid.UUID,
    pairs: list[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Return set of (source, external_id) pairs the user has already viewed."""
    if not pairs:
        return set()
    result = await db.execute(
        select(CandidateView.source, CandidateView.external_id)
        .where(
            CandidateView.user_id == user_id,
            tuple_(CandidateView.source, CandidateView.external_id).in_(pairs),
        )
    )
    return set(result.all())


# ── search history ────────────────────────────────────────────────

@router.get("/api/search/history")
async def search_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return user's search history (recent first)."""
    offset = (page - 1) * per_page
    result = await db.execute(
        select(SearchModel)
        .where(SearchModel.user_id == user.id)
        .order_by(SearchModel.created_at.desc())
        .limit(per_page)
        .offset(offset)
    )
    searches = result.scalars().all()
    count_row = await db.execute(
        select(func.count()).select_from(SearchModel).where(SearchModel.user_id == user.id)
    )
    total = count_row.scalar() or 0
    return {
        "items": [
            {
                "id": str(s.id),
                "query_text": s.query_text,
                "query_params": s.query_params or {},
                "sources": s.sources,
                "total_results": s.total_results or 0,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in searches
        ],
        "total": total,
    }


@router.get("/api/search/{search_id}")
async def get_search(
    search_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get search metadata (for restore params)."""
    try:
        sid = _uuid.UUID(search_id)
    except ValueError:
        return {"error": True, "message": "Недействительный search_id"}
    search = await db.get(SearchModel, sid)
    if search is None or search.user_id != user.id:
        return {"error": True, "message": "Поиск не найден"}
    return {
        "error": False,
        "id": str(search.id),
        "query_text": search.query_text,
        "query_params": search.query_params or {},
        "sources": search.sources,
    }


@router.get("/api/search/{search_id}/results")
async def search_results(
    search_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Load candidates from a previous search."""
    try:
        sid = _uuid.UUID(search_id)
    except ValueError:
        return {"error": True, "message": "Недействительный search_id"}
    search = await db.get(SearchModel, sid)
    if search is None or search.user_id != user.id:
        return {"error": True, "message": "Поиск не найден"}
    result = await db.execute(
        select(CandidateModel).where(CandidateModel.search_id == sid)
    )
    candidates = result.scalars().all()
    pairs = [(c.source or "hh", c.external_id or "") for c in candidates if c.external_id]
    viewed_keys = await _load_viewed_keys(db, user.id, pairs)
    return {
        "error": False,
        "search_id": search_id,
        "total_found": search.total_results or len(candidates),
        "candidates": [_candidate_to_ui(c, viewed_keys) for c in candidates],
    }


# ── candidate view tracking ───────────────────────────────────────

@router.post("/api/candidate-view")
async def mark_candidate_viewed(
    source: str = Body(..., embed=True),
    external_id: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that the user has viewed a candidate profile."""
    stmt = pg_insert(CandidateView).values(
        user_id=user.id,
        source=source,
        external_id=external_id,
    ).on_conflict_do_nothing(
        constraint="uq_candidate_views_user_source_ext",
    )
    await db.execute(stmt)
    await db.flush()
    return {"ok": True}


# ── search endpoint ───────────────────────────────────────────────

def _normalize_sources(s: str) -> tuple[bool, bool]:
    """Parse sources: 'hh' | 'linkedin' | 'both' -> (use_hh, use_linkedin)."""
    s = (s or "both").lower().strip()
    if s == "hh":
        return True, False
    if s == "linkedin":
        return False, True
    return True, True


async def _get_linkedin_credential(user: User, db: AsyncSession) -> Credential | None:
    """Load the user's LinkedIn credential if active."""
    result = await db.execute(
        select(Credential).where(
            Credential.user_id == user.id,
            Credential.provider == "linkedin",
            Credential.status.in_(["active", "expired"]),
        )
    )
    return result.scalar_one_or_none()


# ── search endpoint ───────────────────────────────────────────────

@router.get("/api/search")
async def search_resumes(
    request: Request,
    search_text: str = Query("", description="Поиск в названии резюме"),
    search_in_positions: bool = Query(False, description="Искать также в должностях"),
    search_company: str = Query("", description="Поиск по компании/отрасли"),
    search_skills: str = Query("", description="Поиск в навыках"),
    search_skills_field: str = Query("skills", description="Где искать навыки: skills | everywhere"),
    exclude_title: str = Query("", description="Исключить из названия резюме"),
    exclude_company: str = Query("", description="Исключить компанию/отрасль"),
    experience: list[str] = Query([], description="Опыт"),
    area: int = Query(HH_DEFAULT_AREA, description="Регион поиска"),
    period: int = Query(30, description="Период в днях"),
    count: int = Query(50, description="Количество кандидатов"),
    sources: str = Query("both", description="hh | linkedin | both"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    use_hh, use_linkedin = _normalize_sources(sources)

    if not use_hh and not use_linkedin:
        return {"error": True, "message": "Выберите хотя бы один источник поиска."}

    if not search_text.strip() and not search_skills.strip() and not search_company.strip():
        return {"error": True, "message": "Укажите поисковый запрос (название резюме, навыки или компания)."}

    if area not in HH_AREAS_DICT:
        area = HH_DEFAULT_AREA

    count = max(1, min(count, MAX_TOTAL))
    search_record = SearchModel(
        user_id=user.id,
        query_text=search_text or search_skills or search_company or "(пусто)",
        query_params={
            "search_in_positions": search_in_positions,
            "search_company": search_company,
            "search_skills": search_skills,
            "search_skills_field": search_skills_field,
            "exclude_title": exclude_title,
            "exclude_company": exclude_company,
            "experience": experience,
            "area": area,
            "period": period,
            "count": count,
            "sources": sources,
        },
        sources=sources,
        status="running",
    )
    db.add(search_record)
    await db.flush()

    hh_candidates: list[dict] = []
    li_candidates: list[dict] = []
    hh_total_found = 0
    hh_error = None
    li_error = None

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
        li_cred = await _get_linkedin_credential(user, db)
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

    # Persist fresh cookies to credential (created during lazy HTTP auth)
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

    # Save candidates to DB
    for c in hh_candidates:
        db.add(CandidateModel(
            search_id=search_record.id,
            source="hh",
            external_id=c.get("external_id", ""),
            full_name=c["full_name"],
            current_title=c["title"],
            location=c["area"],
            profile_url=c["url"],
            extra_data={
                "photo": c.get("photo"),
                "experience": c.get("experience"),
                "last_work": c.get("last_work"),
                "salary": c.get("salary"),
                "updated_at": c.get("updated_at"),
            },
        ))
    for c in li_candidates:
        ext_id = c.get("urn_id") or ""
        if not ext_id and c.get("url"):
            ext_id = c["url"].split("/in/")[-1].rstrip("/").split("?")[0] or ""
        c.setdefault("source", "linkedin")
        c["external_id"] = ext_id
        db.add(CandidateModel(
            search_id=search_record.id,
            source="linkedin",
            external_id=ext_id,
            full_name=c["full_name"],
            current_title=c["title"],
            location=c["area"],
            profile_url=c["url"],
            extra_data={
                "photo": c.get("photo"),
                "experience": c.get("experience"),
                "last_work": c.get("last_work"),
                "salary": c.get("salary"),
                "updated_at": c.get("updated_at"),
            },
        ))

    # Determine status
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
    await log_action(db, "search", request=request, user_id=user.id, details={
        "query": search_text, "sources": sources, "results": len(candidates),
    })
    await db.flush()

    if not candidates and has_error:
        return {"error": True, "message": "; ".join(m for m in [hh_error, li_error] if m)}

    pairs = [
        (c.get("source", "hh"), c.get("external_id", ""))
        for c in candidates if c.get("external_id")
    ]
    viewed_keys = await _load_viewed_keys(db, user.id, pairs)
    for c in candidates:
        key = (c.get("source", "hh"), c.get("external_id", ""))
        c["is_viewed"] = key in viewed_keys

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


# ── export endpoint ───────────────────────────────────────────────

@router.get("/api/export")
async def export_csv(
    request: Request,
    search_id: str = Query(..., description="ID поиска для экспорта"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export candidates from a previous search as CSV."""
    try:
        sid = _uuid.UUID(search_id)
    except ValueError:
        return {"error": True, "message": "Недействительный search_id"}

    search = await db.get(SearchModel, sid)
    if search is None or search.user_id != user.id:
        return {"error": True, "message": "Поиск не найден"}

    result = await db.execute(
        select(CandidateModel).where(CandidateModel.search_id == sid)
    )
    candidates = result.scalars().all()

    buf = StringIO()
    buf.write("\ufeff")
    header = "Источник;Полное имя;Должность;Последнее место работы;Локация;Опыт;Зарплата;Ссылка;Обновлено;Дата выгрузки\n"
    buf.write(header)
    for c in candidates:
        extra = c.extra_data or {}
        fetched = c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else "—"
        row = ";".join([
            c.source or "hh",
            c.full_name or "—",
            c.current_title or "—",
            extra.get("last_work", "—"),
            c.location or "—",
            extra.get("experience", "—"),
            extra.get("salary", "—"),
            c.profile_url or "",
            extra.get("updated_at", "—"),
            fetched,
        ])
        buf.write(row + "\n")

    await log_action(db, "export_csv", request=request, user_id=user.id, details={
        "search_id": search_id, "count": len(candidates),
    })

    buf.seek(0)
    filename = f"candidates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    encoded = quote(filename, safe="")
    content_disp = f'attachment; filename="candidates_export.csv"; filename*=UTF-8\'\'{encoded}'
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disp},
    )
