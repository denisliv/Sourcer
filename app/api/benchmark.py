"""AlfaHRBenchmark API — salary/vacancy benchmarking endpoints."""

import uuid as _uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import BENCHMARK_PERIOD_OPTIONS
from app.core.database import get_db
from app.models.benchmark import BenchmarkSearch, BenchmarkVacancy
from app.models.user import User
from app.services.audit import log_action
from app.services.benchmark_service import (
    clean_for_json,
    export_to_excel,
    fetch_belarusbank_rates,
    fetch_vacancies,
    filter_outliers_and_compute_stats,
    process_vacancies_data,
    to_table_records,
)

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


# ── helpers ───────────────────────────────────────────────────────


def _save_vacancies(db: AsyncSession, search_id: _uuid.UUID, table_records: list[dict]):
    """Persist filtered vacancy records to the database."""
    for r in table_records:
        db.add(BenchmarkVacancy(
            search_id=search_id,
            name=r.get("name") or "",
            employer_name=r.get("employer_name"),
            area_name=r.get("area_name"),
            specialization=r.get("specialization"),
            experience=r.get("experience"),
            salary_net_from_byn=r.get("salary_net_from_byn"),
            salary_net_to_byn=r.get("salary_net_to_byn"),
            salary_gross_from_byn=r.get("salary_gross_from_byn"),
            salary_gross_to_byn=r.get("salary_gross_to_byn"),
            url=r.get("url"),
            logo_url=r.get("logo_url"),
            published_at=r.get("published_at"),
            loaded_at=r.get("loaded_at"),
        ))


def _vacancy_to_table(v: BenchmarkVacancy) -> dict:
    """Convert a BenchmarkVacancy ORM object to the table-record dict."""
    return {
        "logo_url": v.logo_url,
        "name": v.name,
        "employer_name": v.employer_name,
        "area_name": v.area_name,
        "specialization": v.specialization,
        "experience": v.experience,
        "salary_net_from_byn": v.salary_net_from_byn,
        "salary_net_to_byn": v.salary_net_to_byn,
        "salary_gross_from_byn": v.salary_gross_from_byn,
        "salary_gross_to_byn": v.salary_gross_to_byn,
        "url": v.url,
        "published_at": v.published_at,
        "loaded_at": v.loaded_at,
    }


# ── History & Rerun ─────────────────────────────────────────────────


@router.get("/history")
async def benchmark_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return user's benchmark search history (recent first)."""
    offset = (page - 1) * per_page
    result = await db.execute(
        select(BenchmarkSearch)
        .where(BenchmarkSearch.user_id == user.id)
        .order_by(BenchmarkSearch.created_at.desc())
        .limit(per_page)
        .offset(offset)
    )
    searches = result.scalars().all()
    count_row = await db.execute(
        select(func.count())
        .select_from(BenchmarkSearch)
        .where(BenchmarkSearch.user_id == user.id)
    )
    total = count_row.scalar() or 0
    return {
        "items": [
            {
                "id": str(s.id),
                "query_text": s.query_text,
                "query_params": s.query_params or {},
                "total_vacancies": s.total_vacancies or 0,
                "filtered_count": s.filtered_count or 0,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in searches
        ],
        "total": total,
    }


@router.post("/rerun/{search_id}")
async def benchmark_rerun(
    search_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run a past benchmark search with same params and return results."""
    try:
        sid = _uuid.UUID(search_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Недействительный ID"})
    bench = await db.get(BenchmarkSearch, sid)
    if bench is None or bench.user_id != user.id:
        return JSONResponse(status_code=404, content={"error": "Поиск не найден"})

    params = bench.query_params or {}
    exclude = params.get("exclude", "").strip().replace(" ", ",")
    area_str = params.get("area", "16")
    experience = params.get("experience") or None
    period = int(params.get("period", 30))
    if period not in BENCHMARK_PERIOD_OPTIONS:
        period = 30

    if area_str == "all":
        areas = [16, 1, 2]
    else:
        try:
            areas = [int(area_str)]
        except ValueError:
            areas = [16]

    data = await fetch_vacancies(
        job_query=bench.query_text,
        excluded_text=exclude,
        areas=areas,
        experience=experience,
        period=period,
    )

    rows = await process_vacancies_data(data)

    form_params = {
        "query_text": bench.query_text or "",
        "query_params": {
            "include": bench.query_text or "",
            "exclude": params.get("exclude", ""),
            "area": params.get("area", "16"),
            "experience": params.get("experience", ""),
            "period": int(params.get("period", 30)),
        },
    }

    if not rows:
        new_bench = BenchmarkSearch(
            user_id=user.id,
            query_text=bench.query_text,
            query_params=bench.query_params,
            total_vacancies=0,
            filtered_count=0,
        )
        db.add(new_bench)
        await db.flush()
        await log_action(
            db, "benchmark_rerun", request, user.id,
            {"query": bench.query_text, "original_id": search_id, "results": 0},
        )
        return JSONResponse(
            content={
                "table": [],
                "stats": {
                    "count": 0,
                    "min": None,
                    "max": None,
                    "mean": None,
                    "median": None,
                },
                "salary_avg_gross": [],
                "salary_avg_net": [],
                "total_count": 0,
                "search_id": str(new_bench.id),
                **form_params,
            }
        )

    filtered, stats, salary_avg_gross_list, salary_avg_net_list = (
        filter_outliers_and_compute_stats(rows)
    )
    table_data = to_table_records(filtered)

    new_bench = BenchmarkSearch(
        user_id=user.id,
        query_text=bench.query_text,
        query_params=bench.query_params,
        total_vacancies=len(rows),
        filtered_count=stats["count"],
        stat_min=stats.get("min"),
        stat_max=stats.get("max"),
        stat_mean=stats.get("mean"),
        stat_median=stats.get("median"),
    )
    db.add(new_bench)
    await db.flush()

    _save_vacancies(db, new_bench.id, table_data)
    await db.flush()

    await log_action(
        db, "benchmark_rerun", request, user.id,
        {"query": bench.query_text, "original_id": search_id,
         "total": len(rows), "filtered": stats["count"]},
    )

    return JSONResponse(
        content={
            "table": clean_for_json(table_data),
            "stats": clean_for_json(stats),
            "salary_avg_gross": salary_avg_gross_list,
            "salary_avg_net": salary_avg_net_list,
            "total_count": len(table_data),
            "search_id": str(new_bench.id),
            **form_params,
        }
    )


# ── Search & Export ────────────────────────────────────────────────


class BenchmarkSearchRequest(BaseModel):
    include: str
    exclude: str = ""
    area: str = "16"
    experience: str = ""
    period: int = 30


@router.post("/search")
async def search_vacancies(
    body: BenchmarkSearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job_query = body.include.strip()
    if not job_query:
        return JSONResponse(
            status_code=400,
            content={"error": "Поле 'Название вакансии' не может быть пустым"},
        )

    excluded_text = body.exclude.strip().replace(" ", ",")
    if body.area == "all":
        areas = [16, 1, 2]
    else:
        try:
            areas = [int(body.area)]
        except ValueError:
            areas = [16]

    experience = body.experience if body.experience else None
    period = body.period if body.period in BENCHMARK_PERIOD_OPTIONS else 30

    data = await fetch_vacancies(
        job_query=job_query,
        excluded_text=excluded_text,
        areas=areas,
        experience=experience,
        period=period,
    )

    rows = await process_vacancies_data(data)

    if not rows:
        bench = BenchmarkSearch(
            user_id=user.id,
            query_text=job_query,
            query_params={
                "exclude": body.exclude,
                "area": body.area,
                "experience": body.experience,
                "period": body.period,
            },
            total_vacancies=0,
            filtered_count=0,
        )
        db.add(bench)
        await db.flush()
        await log_action(
            db, "benchmark_search", request, user.id, {"query": job_query, "results": 0}
        )

        return JSONResponse(
            content={
                "table": [],
                "stats": {
                    "count": 0,
                    "min": None,
                    "max": None,
                    "mean": None,
                    "median": None,
                },
                "salary_avg_gross": [],
                "salary_avg_net": [],
                "total_count": 0,
                "search_id": str(bench.id),
            }
        )

    filtered, stats, salary_avg_gross_list, salary_avg_net_list = (
        filter_outliers_and_compute_stats(rows)
    )
    table_data = to_table_records(filtered)

    bench = BenchmarkSearch(
        user_id=user.id,
        query_text=job_query,
        query_params={
            "exclude": body.exclude,
            "area": body.area,
            "experience": body.experience,
            "period": body.period,
        },
        total_vacancies=len(rows),
        filtered_count=stats["count"],
        stat_min=stats.get("min"),
        stat_max=stats.get("max"),
        stat_mean=stats.get("mean"),
        stat_median=stats.get("median"),
    )
    db.add(bench)
    await db.flush()

    _save_vacancies(db, bench.id, table_data)
    await db.flush()

    await log_action(
        db,
        "benchmark_search",
        request,
        user.id,
        {"query": job_query, "total": len(rows), "filtered": stats["count"]},
    )

    return JSONResponse(
        content={
            "table": clean_for_json(table_data),
            "stats": clean_for_json(stats),
            "salary_avg_gross": salary_avg_gross_list,
            "salary_avg_net": salary_avg_net_list,
            "total_count": len(table_data),
            "search_id": str(bench.id),
        }
    )


@router.get("/export")
async def benchmark_export_excel(
    request: Request,
    search_id: str = Query(..., description="ID поиска для экспорта"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export vacancies from a previous benchmark search as Excel (loaded from DB)."""
    try:
        sid = _uuid.UUID(search_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"error": "Недействительный search_id"}
        )

    bench = await db.get(BenchmarkSearch, sid)
    if bench is None or bench.user_id != user.id:
        return JSONResponse(status_code=404, content={"error": "Поиск не найден"})

    result = await db.execute(
        select(BenchmarkVacancy).where(BenchmarkVacancy.search_id == sid)
    )
    vacancies = result.scalars().all()

    if not vacancies:
        return JSONResponse(
            status_code=404, content={"error": "Нет данных для выгрузки"}
        )

    table_records = [_vacancy_to_table(v) for v in vacancies]
    output = export_to_excel(table_records)

    await log_action(db, "benchmark_export", request=request, user_id=user.id, details={
        "search_id": search_id, "count": len(vacancies),
    })

    job_query = bench.query_text or "vacancies"
    filename = f"vacancies_{job_query[:30].replace(' ', '_')}.xlsx"
    safe_ascii = "benchmark_export.xlsx"
    encoded = quote(filename, safe="")
    content_disp = f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{encoded}"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disp},
    )


@router.get("/rates")
async def get_rates(user: User = Depends(get_current_user)):
    rates = await fetch_belarusbank_rates()
    if rates:
        return JSONResponse(
            content={
                "source": "belarusbank_api",
                "rates": {k: round(v, 4) for k, v in rates.items()},
            }
        )
    from app.services.benchmark_service import (
        RATE_EUR_TO_BYN_FALLBACK,
        RATE_RUR_TO_BYN_FALLBACK,
        RATE_USD_TO_BYN_FALLBACK,
    )

    return JSONResponse(
        content={
            "source": "fallback",
            "rates": {
                "USD": RATE_USD_TO_BYN_FALLBACK,
                "EUR": RATE_EUR_TO_BYN_FALLBACK,
                "RUR": RATE_RUR_TO_BYN_FALLBACK,
                "RUB": RATE_RUR_TO_BYN_FALLBACK,
            },
        }
    )
