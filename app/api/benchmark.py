"""AlfaHRBenchmark API — salary/vacancy benchmarking endpoints."""

import uuid as _uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import BENCHMARK_PERIOD_OPTIONS
from app.core.database import get_db
from app.models.benchmark import BenchmarkSearch
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
        select(func.count()).select_from(BenchmarkSearch).where(BenchmarkSearch.user_id == user.id)
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

    if not rows:
        return JSONResponse(content={
            "table": [],
            "stats": {"count": 0, "min": None, "max": None, "mean": None, "median": None},
            "salary_avg_gross": [],
            "salary_avg_net": [],
            "total_count": 0,
        })

    filtered, stats, salary_avg_gross_list, salary_avg_net_list = (
        filter_outliers_and_compute_stats(rows)
    )
    table_data = to_table_records(filtered)

    return JSONResponse(content={
        "table": clean_for_json(table_data),
        "stats": clean_for_json(stats),
        "salary_avg_gross": salary_avg_gross_list,
        "salary_avg_net": salary_avg_net_list,
        "total_count": len(table_data),
    })


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
                "exclude": body.exclude, "area": body.area,
                "experience": body.experience, "period": body.period,
            },
            total_vacancies=0, filtered_count=0,
        )
        db.add(bench)
        await log_action(db, "benchmark_search", request, user.id, {"query": job_query, "results": 0})

        return JSONResponse(content={
            "table": [], "stats": {"count": 0, "min": None, "max": None, "mean": None, "median": None},
            "salary_avg_gross": [], "salary_avg_net": [], "total_count": 0,
        })

    filtered, stats, salary_avg_gross_list, salary_avg_net_list = (
        filter_outliers_and_compute_stats(rows)
    )
    table_data = to_table_records(filtered)

    bench = BenchmarkSearch(
        user_id=user.id,
        query_text=job_query,
        query_params={
            "exclude": body.exclude, "area": body.area,
            "experience": body.experience, "period": body.period,
        },
        total_vacancies=len(rows),
        filtered_count=stats["count"],
        stat_min=stats.get("min"),
        stat_max=stats.get("max"),
        stat_mean=stats.get("mean"),
        stat_median=stats.get("median"),
    )
    db.add(bench)

    await log_action(
        db, "benchmark_search", request, user.id,
        {"query": job_query, "total": len(rows), "filtered": stats["count"]},
    )

    return JSONResponse(content={
        "table": clean_for_json(table_data),
        "stats": clean_for_json(stats),
        "salary_avg_gross": salary_avg_gross_list,
        "salary_avg_net": salary_avg_net_list,
        "total_count": len(table_data),
    })


@router.post("/export-excel")
async def benchmark_export_excel(
    body: BenchmarkSearchRequest,
    user: User = Depends(get_current_user),
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
        return JSONResponse(status_code=404, content={"error": "Нет данных для выгрузки"})

    filtered, _, _, _ = filter_outliers_and_compute_stats(rows)
    table_records = to_table_records(filtered)
    output = export_to_excel(table_records)

    filename = f"vacancies_{job_query[:30].replace(' ', '_')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/rates")
async def get_rates(user: User = Depends(get_current_user)):
    rates = await fetch_belarusbank_rates()
    if rates:
        return JSONResponse(content={
            "source": "belarusbank_api",
            "rates": {k: round(v, 4) for k, v in rates.items()},
        })
    from app.services.benchmark_service import (
        RATE_EUR_TO_BYN_FALLBACK,
        RATE_RUR_TO_BYN_FALLBACK,
        RATE_USD_TO_BYN_FALLBACK,
    )
    return JSONResponse(content={
        "source": "fallback",
        "rates": {
            "USD": RATE_USD_TO_BYN_FALLBACK,
            "EUR": RATE_EUR_TO_BYN_FALLBACK,
            "RUR": RATE_RUR_TO_BYN_FALLBACK,
            "RUB": RATE_RUR_TO_BYN_FALLBACK,
        },
    })
