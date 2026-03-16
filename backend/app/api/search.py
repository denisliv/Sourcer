"""Search and export routes: candidate search across HH and LinkedIn, CSV export."""

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.constants import HH_AREAS_DICT, HH_DEFAULT_AREA
from app.core.database import get_db
from app.models.candidate import Candidate as CandidateModel
from app.models.candidate_view import CandidateView
from app.models.search import Search as SearchModel
from app.models.user import User
from app.services.audit import log_action
from app.services.hh_service import MAX_TOTAL, get_hh_headers
from app.services.search_service import (
    build_evaluation_stream,
    execute_search,
    normalize_sources,
)

router = APIRouter(tags=["search"])


# ── helpers ───────────────────────────────────────────────────────

def _candidate_to_ui(
    c: CandidateModel,
    viewed_keys: set[tuple[str, str]] | None = None,
) -> dict:
    """Convert Candidate model to UI format."""
    fetched = c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else "—"
    source = c.source or "hh"
    ext_id = c.external_id or ""
    is_viewed = (source, ext_id) in viewed_keys if viewed_keys else False
    return {
        "source": source,
        "external_id": ext_id,
        "is_viewed": is_viewed,
        "photo": c.photo,
        "full_name": c.full_name or "—",
        "title": c.current_title or "—",
        "area": c.location or "—",
        "experience": c.experience or "—",
        "last_work": c.last_work or "—",
        "salary": c.salary or "—",
        "url": c.profile_url or "",
        "updated_at": c.resume_updated_at or "—",
        "fetched_at": fetched,
        "ai_score": c.ai_score,
        "ai_summary": c.ai_summary or "",
        "ai_status": c.ai_status or "",
    }


async def _load_viewed_keys(
    db: AsyncSession,
    user_id: _uuid.UUID,
    pairs: list[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Return set of (source, external_id) pairs the user has already viewed."""
    if not pairs:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.candidate_view_ttl_days)
    result = await db.execute(
        select(CandidateView.source, CandidateView.external_id)
        .where(
            CandidateView.user_id == user_id,
            CandidateView.viewed_at >= cutoff,
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
        select(CandidateModel)
        .where(CandidateModel.search_id == sid)
        .order_by(CandidateModel.position)
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
    use_hh, use_linkedin = normalize_sources(sources)

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

    result = await execute_search(
        user=user,
        db=db,
        search_record=search_record,
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
        use_hh=use_hh,
        use_linkedin=use_linkedin,
    )

    await log_action(db, "search", request=request, user_id=user.id, details={
        "query": search_text, "sources": sources, "results": result.get("returned", 0),
    })
    await db.flush()

    if result.get("error"):
        return result

    candidates = result.get("candidates", [])
    pairs = [
        (c.get("source", "hh"), c.get("external_id", ""))
        for c in candidates if c.get("external_id")
    ]
    viewed_keys = await _load_viewed_keys(db, user.id, pairs)
    for c in candidates:
        key = (c.get("source", "hh"), c.get("external_id", ""))
        c["is_viewed"] = key in viewed_keys

    return result


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
        select(CandidateModel)
        .where(CandidateModel.search_id == sid)
        .order_by(CandidateModel.position)
    )
    candidates = result.scalars().all()

    buf = StringIO()
    buf.write("\ufeff")
    header = "Источник;Полное имя;Должность;Последнее место работы;Локация;Опыт;Зарплата;Ссылка;Обновлено;Дата выгрузки\n"
    buf.write(header)
    for c in candidates:
        fetched = c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else "—"
        row = ";".join([
            c.source or "hh",
            c.full_name or "—",
            c.current_title or "—",
            c.last_work or "—",
            c.location or "—",
            c.experience or "—",
            c.salary or "—",
            c.profile_url or "",
            c.resume_updated_at or "—",
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


# ── AI evaluation endpoint (SSE) ─────────────────────────────────

@router.post("/api/search/{search_id}/evaluate")
async def evaluate_search_candidates(
    search_id: str,
    request: Request,
    job_description: str = Body(..., embed=True),
    reset: bool = Body(False, embed=True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate candidates via LLM. Returns SSE stream with per-candidate results."""
    try:
        sid = _uuid.UUID(search_id)
    except ValueError:
        return {"error": True, "message": "Недействительный search_id"}

    search = await db.get(SearchModel, sid)
    if search is None or search.user_id != user.id:
        return {"error": True, "message": "Поиск не найден"}

    if not job_description.strip():
        return {"error": True, "message": "Описание вакансии не может быть пустым."}

    result = await db.execute(
        select(CandidateModel)
        .where(CandidateModel.search_id == sid)
        .order_by(CandidateModel.position)
    )
    all_candidates = result.scalars().all()

    hh_candidates = [c for c in all_candidates if c.source == "hh"]
    if not hh_candidates:
        return {"error": True, "message": "Нет HH-кандидатов для оценки."}

    headers = await get_hh_headers(user, db)
    if headers is None:
        return {"error": True, "message": "HH credentials не настроены. Перейдите в Личный кабинет."}

    search_area = (search.query_params or {}).get("area", HH_DEFAULT_AREA)

    return StreamingResponse(
        build_evaluation_stream(
            db=db,
            user=user,
            hh_candidates=hh_candidates,
            job_description=job_description,
            reset=reset,
            area=int(search_area),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
