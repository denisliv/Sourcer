import asyncio
import math
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --------------- Config ---------------
BASE_DIR = Path(__file__).resolve().parent
with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

ACCESS_TOKEN: str = config["ACCESS_TOKEN"]
USER_AGENT: str = config["User_Agent"]
API_URL: str = config["API_URL"]
HOST: str = config["HOST"]
AREA: int = config["AREA"]

HEADERS = {
    "HH-User-Agent": USER_AGENT,
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}

MAX_PER_PAGE = 50
MAX_TOTAL = 2000

# --------------- App ---------------
app = FastAPI(title="AlfaHRSourcer")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --------------- helpers ---------------


def _build_params(
    search_text: str,
    search_fields: list[str],
    exclude_text: str,
    exclude_fields: list[str],
    experience: list[str],
    period: int,
    page: int,
    per_page: int,
) -> list[tuple[str, str]]:
    """Build list-of-tuples params preserving duplicate keys order."""
    params: list[tuple[str, str]] = [
        ("host", HOST),
    ]

    # --- search block ---
    params.append(("text", search_text))
    params.append(("text.logic", "all"))
    params.append(("text.field", ",".join(search_fields)))
    params.append(("text.period", ""))

    # --- experience (multiple allowed) ---
    for exp in experience:
        params.append(("experience", exp))

    # --- exclude block ---
    if exclude_text.strip():
        params.append(("text", exclude_text))
        params.append(("text.logic", "except"))
        params.append(("text.field", ",".join(exclude_fields)))
        params.append(("text.period", ""))

    # --- common ---
    params.append(("period", str(period)))
    params.append(("area", str(AREA)))
    params.append(("per_page", str(per_page)))
    params.append(("page", str(page)))

    return params


def _format_experience(months: Optional[int]) -> str:
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


def _format_salary(salary: Optional[dict]) -> str:
    if not salary:
        return "—"
    amount = salary.get("amount")
    currency = salary.get("currency", "")
    if amount is None:
        return "—"
    currency_map = {
        "RUR": "₽",
        "USD": "$",
        "EUR": "€",
        "BYR": "BYN",
        "KZT": "₸",
        "UAH": "₴",
    }
    symbol = currency_map.get(currency, currency)
    return f"{amount:,.0f} {symbol}".replace(",", " ")


def _parse_item(item: dict) -> dict:
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
    if (
        item.get("total_experience")
        and item["total_experience"].get("months") is not None
    ):
        total_exp_months = item["total_experience"]["months"]

    return {
        "photo": photo,
        "full_name": full_name,
        "title": item.get("title", "—"),
        "area": area_name,
        "experience": _format_experience(total_exp_months),
        "salary": _format_salary(item.get("salary")),
        "url": item.get("alternate_url", ""),
        "updated_at": item.get("updated_at", "—"),
        "fetched_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


# --------------- API endpoints ---------------


@app.get("/api/search")
async def search_resumes(
    search_text: str = Query(..., description="Поисковый запрос"),
    search_fields: list[str] = Query(["title"], description="Где искать"),
    exclude_text: str = Query("", description="Исключить"),
    exclude_fields: list[str] = Query([], description="Где исключать"),
    experience: list[str] = Query([], description="Опыт"),
    period: int = Query(30, description="Период в днях"),
    count: int = Query(50, description="Количество кандидатов"),
):
    # Clamp count
    count = max(1, min(count, MAX_TOTAL))
    per_page = min(count, MAX_PER_PAGE)
    total_pages = math.ceil(count / per_page)

    candidates: list[dict] = []

    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        for page in range(total_pages):
            current_per_page = min(per_page, count - len(candidates))
            params = _build_params(
                search_text=search_text,
                search_fields=search_fields,
                exclude_text=exclude_text,
                exclude_fields=exclude_fields,
                experience=experience,
                period=period,
                page=page,
                per_page=current_per_page,
            )
            resp = await client.get(API_URL, params=params)
            if resp.status_code != 200:
                return {
                    "error": True,
                    "message": f"HH API вернул статус {resp.status_code}",
                    "detail": resp.text,
                }
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                candidates.append(_parse_item(item))
                if len(candidates) >= count:
                    break
            if len(candidates) >= count:
                break
            # Small delay to avoid rate limits
            await asyncio.sleep(0.25)

    return {
        "error": False,
        "total_found": data.get("found", 0) if candidates else 0,
        "returned": len(candidates),
        "candidates": candidates,
    }


@app.get("/api/export")
async def export_csv(
    search_text: str = Query(...),
    search_fields: list[str] = Query(["title"]),
    exclude_text: str = Query(""),
    exclude_fields: list[str] = Query([]),
    experience: list[str] = Query([]),
    period: int = Query(30),
    count: int = Query(50),
):
    result = await search_resumes(
        search_text=search_text,
        search_fields=search_fields,
        exclude_text=exclude_text,
        exclude_fields=exclude_fields,
        experience=experience,
        period=period,
        count=count,
    )
    if result.get("error"):
        return result

    buf = StringIO()
    buf.write("\ufeff")
    header = (
        "Полное имя;Должность;Локация;Опыт;Зарплата;Ссылка;Обновлено;Дата выгрузки\n"
    )
    buf.write(header)
    for c in result["candidates"]:
        row = ";".join(
            [
                c["full_name"],
                c["title"],
                c["area"],
                c["experience"],
                c["salary"],
                c["url"],
                c["updated_at"],
                c["fetched_at"],
            ]
        )
        buf.write(row + "\n")

    buf.seek(0)
    filename = f"candidates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
