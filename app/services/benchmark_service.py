"""AlfaHRBenchmark — salary/vacancy benchmarking service.

Fetches vacancy data from HeadHunter API, converts salaries to BYN,
filters outliers, and computes statistics (min/max/mean/median).
"""

import io
import math
import statistics
from datetime import datetime
from typing import Any

import httpx
from openpyxl import Workbook

from app.core.config import HH_APP_TOKEN

# --------------- Exchange rates ---------------

BELARUSBANK_API_URL = "https://belarusbank.by/api/kursExchange"
BELARUSBANK_API_CITY = "Минск"

RATE_RUR_TO_BYN_FALLBACK = 3.705 / 100
RATE_USD_TO_BYN_FALLBACK = 2.85
RATE_EUR_TO_BYN_FALLBACK = 3.38

CACHE_TTL_SECONDS = 3600
_exchange_rates_cache: dict[str, float] = {}
_exchange_rates_updated_at: datetime | None = None

API_CURRENCY_MAP = {
    "USD": ("USD_in", 1),
    "EUR": ("EUR_in", 1),
    "RUR": ("RUB_in", 100),
    "RUB": ("RUB_in", 100),
    "GBP": ("GBP_in", 1),
    "CAD": ("CAD_in", 1),
    "PLN": ("PLN_in", 1),
    "UAH": ("UAH_in", 100),
    "SEK": ("SEK_in", 10),
    "CHF": ("CHF_in", 10),
    "JPY": ("JPY_in", 100),
    "CNY": ("CNY_in", 10),
    "CZK": ("CZK_in", 100),
    "NOK": ("NOK_in", 10),
}

# --------------- HH API ---------------

PER_PAGE = 50
MAX_VACANCIES = 2000
NDFL_RATE = 0.14
MIN_REASONABLE_SALARY_BYN = 500


def _get_host_for_area(area_id: int) -> str:
    return "rabota.by" if area_id == 16 else "hh.ru"


async def fetch_exchange_rates(
    city: str = BELARUSBANK_API_CITY,
) -> dict[str, float] | None:
    """Load exchange rates from Belarusbank API (async)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(BELARUSBANK_API_URL, params={"city": city})
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not isinstance(data, list) or not data:
        return None

    result: dict[str, float] = {}
    for api_currency, (api_key, divisor) in API_CURRENCY_MAP.items():
        for branch in data:
            raw = branch.get(api_key)
            if raw is None:
                continue
            try:
                val = float(str(raw).replace(",", "."))
            except (ValueError, TypeError):
                continue
            if val > 0:
                result[api_currency] = val / divisor
                break

    return result if result else None


async def get_exchange_rates() -> dict[str, float]:
    """Return cached exchange rates; fallback to static values on error."""
    global _exchange_rates_cache, _exchange_rates_updated_at
    now = datetime.now()
    if _exchange_rates_cache and _exchange_rates_updated_at:
        elapsed = (now - _exchange_rates_updated_at).total_seconds()
        if elapsed < CACHE_TTL_SECONDS:
            return _exchange_rates_cache

    rates = await fetch_exchange_rates()
    if rates:
        _exchange_rates_cache = rates.copy()
        _exchange_rates_updated_at = now
        return _exchange_rates_cache

    return {
        "USD": RATE_USD_TO_BYN_FALLBACK,
        "EUR": RATE_EUR_TO_BYN_FALLBACK,
        "RUR": RATE_RUR_TO_BYN_FALLBACK,
        "RUB": RATE_RUR_TO_BYN_FALLBACK,
        "BYN": 1.0,
        "BYR": 1.0,
    }


# --------------- Helpers ---------------


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            float_val = float(value.item())
        else:
            float_val = float(value)
        if math.isinf(float_val) or math.isnan(float_val):
            return None
        return float_val
    except (ValueError, TypeError, OverflowError):
        return None


def _convert_to_byn(
    amount: float | None, currency: str | None, rates: dict[str, float]
) -> float | None:
    if amount is None or currency is None:
        return None
    upper = currency.upper()
    if upper in ("BYN", "BYR"):
        return amount
    rate = rates.get(upper)
    return amount * rate if rate is not None else None


def _salary_gross_to_net(gross: float) -> float:
    return gross * (1 - NDFL_RATE)


def _salary_net_to_gross(net: float) -> float | None:
    return net / (1 - NDFL_RATE) if net else None


def _avg_salary(from_val: float | None, to_val: float | None) -> float | None:
    if from_val is not None and to_val is not None:
        return (from_val + to_val) / 2
    return from_val if from_val is not None else to_val


def _salary_lower_bound(from_val: Any, to_val: Any) -> float | None:
    f = _safe_float(from_val)
    t = _safe_float(to_val)
    if f is not None and t is not None:
        return min(f, t)
    return f if f is not None else t


def _round_salary(val: Any) -> float | None:
    f = _safe_float(val)
    return round(f) if f is not None else None


def clean_for_json(obj: Any) -> Any:
    """Recursively replace inf/nan with None for JSON safety."""
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_for_json(item) for item in obj]
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if obj is None:
        return None
    if hasattr(obj, "item"):
        try:
            val = obj.item()
            return clean_for_json(val)
        except Exception:
            return None
    return obj


# --------------- Core logic ---------------


async def fetch_vacancies(
    job_query: str,
    excluded_text: str,
    areas: list[int],
    experience: str | None,
    period: int,
    industries: list[int] | None = None,
) -> list[dict]:
    """Fetch vacancies from the HH vacancies API (app-level token, async)."""
    data: list[dict] = []
    headers = {"Authorization": f"Bearer {HH_APP_TOKEN}"}

    async with httpx.AsyncClient(timeout=15) as client:
        for area in areas:
            host = _get_host_for_area(area)
            total_fetched = 0
            page = 0

            while total_fetched < MAX_VACANCIES:
                params: dict[str, Any] = {
                    "host": host,
                    "text": f"{job_query.strip()}",
                    "search_field": "name",
                    "area": area,
                    "only_with_salary": True,
                    "per_page": PER_PAGE,
                    "page": page,
                    "period": period,
                }
                if experience:
                    params["experience"] = experience
                if excluded_text.strip():
                    params["excluded_text"] = excluded_text.strip()
                if industries:
                    params["industry"] = industries

                try:
                    r = await client.get(
                        "https://api.hh.ru/vacancies",
                        params=params,
                        headers=headers,
                    )
                    r.raise_for_status()
                    response_data = r.json()
                except httpx.HTTPError:
                    break

                items = response_data.get("items", [])
                if not items:
                    break

                data.append(response_data)
                total_fetched += len(items)

                if len(items) < PER_PAGE or total_fetched >= MAX_VACANCIES:
                    break
                page += 1

    return data


async def process_vacancies_data(data: list[dict]) -> list[dict]:
    """Process raw HH API responses into normalized rows with BYN salaries."""
    if not data:
        return []

    all_items: list[dict] = []
    for response in data:
        all_items.extend(response.get("items", []))
    if not all_items:
        return []

    rates = await get_exchange_rates()
    rows: list[dict] = []

    for item in all_items:
        employer = item.get("employer") or {}
        logo_url = None
        if employer.get("logo_urls"):
            logo_url = employer["logo_urls"].get("90") or employer["logo_urls"].get(
                "240"
            )

        area = item.get("area") or {}
        area_name = area.get("name", "") if isinstance(area, dict) else ""

        prof_roles = item.get("professional_roles") or []
        specialization = ", ".join(
            r.get("name", "") for r in prof_roles if isinstance(r, dict)
        )

        exp = item.get("experience") or {}
        experience_str = exp.get("name", "") if isinstance(exp, dict) else ""

        salary_net_from_byn = None
        salary_net_to_byn = None
        salary_gross_from_byn = None
        salary_gross_to_byn = None
        salary = item.get("salary")
        if salary and isinstance(salary, dict):
            from_val = salary.get("from")
            to_val = salary.get("to")
            currency = salary.get("currency", "RUR")
            gross = salary.get("gross", True)

            if from_val is not None or to_val is not None:
                if gross:
                    gross_from, gross_to = from_val, to_val
                    net_from = _salary_gross_to_net(from_val) if from_val else None
                    net_to = _salary_gross_to_net(to_val) if to_val else None
                else:
                    net_from, net_to = from_val, to_val
                    gross_from = _salary_net_to_gross(from_val) if from_val else None
                    gross_to = _salary_net_to_gross(to_val) if to_val else None

                salary_net_from_byn = _safe_float(
                    _convert_to_byn(net_from, currency, rates)
                )
                salary_net_to_byn = _safe_float(
                    _convert_to_byn(net_to, currency, rates)
                )
                salary_gross_from_byn = _safe_float(
                    _convert_to_byn(gross_from, currency, rates)
                )
                salary_gross_to_byn = _safe_float(
                    _convert_to_byn(gross_to, currency, rates)
                )

        published_raw = item.get("published_at") or ""
        published_at = ""
        if published_raw:
            try:
                dt = datetime.strptime(published_raw[:19], "%Y-%m-%dT%H:%M:%S")
                published_at = dt.strftime("%d.%m.%Y %H:%M")
            except (ValueError, TypeError):
                published_at = (
                    published_raw[:10] if len(published_raw) >= 10 else published_raw
                )

        rows.append(
            {
                "logo_url": logo_url,
                "name": item.get("name") or "",
                "employer_name": employer.get("name") or "",
                "area_name": area_name,
                "specialization": specialization,
                "experience": experience_str,
                "salary_net_from_byn": salary_net_from_byn,
                "salary_net_to_byn": salary_net_to_byn,
                "salary_gross_from_byn": salary_gross_from_byn,
                "salary_gross_to_byn": salary_gross_to_byn,
                "published_at": published_at,
                "loaded_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "url": item.get("alternate_url") or "",
            }
        )

    return rows


def filter_outliers_and_compute_stats(
    rows: list[dict],
) -> tuple[list[dict], dict, list[int], list[int]]:
    """Filter salary outliers (IQR method) and compute stats.

    Returns (filtered_rows, stats_dict, salary_avg_gross_list, salary_avg_net_list).
    """
    for row in rows:
        row["_salary_avg_gross"] = _avg_salary(
            row["salary_gross_from_byn"], row["salary_gross_to_byn"]
        )
        row["_salary_avg_net"] = _avg_salary(
            row["salary_net_from_byn"], row["salary_net_to_byn"]
        )
        row["_salary_lower_bound"] = _salary_lower_bound(
            row["salary_gross_from_byn"], row["salary_gross_to_byn"]
        )

    rows_above_min = [
        r
        for r in rows
        if r["_salary_lower_bound"] is None
        or r["_salary_lower_bound"] >= MIN_REASONABLE_SALARY_BYN
    ]

    salary_values = [
        r["_salary_avg_gross"]
        for r in rows_above_min
        if r["_salary_avg_gross"] is not None
    ]
    lower, upper = None, None
    if len(salary_values) >= 4:
        q1 = statistics.quantiles(salary_values, n=4)[0]
        q3 = statistics.quantiles(salary_values, n=4)[2]
        iqr = q3 - q1
        if iqr > 0:
            lower = max(q1 - 1.5 * iqr, MIN_REASONABLE_SALARY_BYN)
            upper = q3 + 1.5 * iqr

    if lower is not None and upper is not None:
        filtered = [
            r
            for r in rows_above_min
            if r["_salary_avg_gross"] is None
            or (lower <= r["_salary_avg_gross"] <= upper)
        ]
    else:
        filtered = rows_above_min

    for r in rows:
        r.pop("_salary_avg_gross", None)
        r.pop("_salary_avg_net", None)
        r.pop("_salary_lower_bound", None)

    salary_avg_gross_list: list[int] = []
    salary_avg_net_list: list[int] = []
    for r in filtered:
        avg_g = _avg_salary(r["salary_gross_from_byn"], r["salary_gross_to_byn"])
        avg_n = _avg_salary(r["salary_net_from_byn"], r["salary_net_to_byn"])
        if avg_g is not None:
            salary_avg_gross_list.append(round(_safe_float(avg_g)))
        if avg_n is not None:
            salary_avg_net_list.append(round(_safe_float(avg_n)))

    values_avg: list[float] = []
    floors: list[float] = []
    ceilings: list[float] = []
    for r in filtered:
        f_from = _safe_float(r["salary_gross_from_byn"])
        f_to = _safe_float(r["salary_gross_to_byn"])
        avg = _avg_salary(r["salary_gross_from_byn"], r["salary_gross_to_byn"])
        if avg is not None:
            values_avg.append(avg)
        floor = (
            min(f_from, f_to)
            if (f_from is not None and f_to is not None)
            else (f_from or f_to)
        )
        ceiling = (
            max(f_from, f_to)
            if (f_from is not None and f_to is not None)
            else (f_from or f_to)
        )
        if floor is not None and floor >= MIN_REASONABLE_SALARY_BYN:
            floors.append(floor)
        if ceiling is not None:
            ceilings.append(ceiling)

    def safe_stat(values: list, func) -> int | None:
        if not values:
            return None
        try:
            v = _safe_float(func(values))
            return round(v) if v is not None else None
        except Exception:
            return None

    stats = {
        "count": len(filtered),
        "min": safe_stat(floors, min) if floors else None,
        "max": safe_stat(ceilings, max) if ceilings else None,
        "mean": safe_stat(values_avg, statistics.mean) if values_avg else None,
        "median": safe_stat(values_avg, statistics.median) if values_avg else None,
    }

    return filtered, stats, salary_avg_gross_list, salary_avg_net_list


def to_table_records(rows: list[dict]) -> list[dict]:
    """Round salaries to integers for display."""
    return [
        {
            "logo_url": r["logo_url"],
            "name": r["name"],
            "employer_name": r["employer_name"],
            "area_name": r["area_name"],
            "specialization": r["specialization"],
            "experience": r["experience"],
            "salary_net_from_byn": _round_salary(r["salary_net_from_byn"]),
            "salary_net_to_byn": _round_salary(r["salary_net_to_byn"]),
            "salary_gross_from_byn": _round_salary(r["salary_gross_from_byn"]),
            "salary_gross_to_byn": _round_salary(r["salary_gross_to_byn"]),
            "url": r["url"],
            "published_at": r["published_at"],
            "loaded_at": r["loaded_at"],
        }
        for r in rows
    ]


def export_to_excel(rows: list[dict]) -> io.BytesIO:
    """Generate an Excel file from vacancy records."""
    headers = [
        "Логотип",
        "Название вакансии",
        "Название компании",
        "Локация",
        "Специализация",
        "Опыт работы",
        "ЗП net от (BYN)",
        "ЗП net до (BYN)",
        "ЗП gross от (BYN)",
        "ЗП gross до (BYN)",
        "Ссылка на вакансию",
        "Дата публикации",
        "Дата загрузки",
    ]
    keys = [
        "logo_url",
        "name",
        "employer_name",
        "area_name",
        "specialization",
        "experience",
        "salary_net_from_byn",
        "salary_net_to_byn",
        "salary_gross_from_byn",
        "salary_gross_to_byn",
        "url",
        "published_at",
        "loaded_at",
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Вакансии"
    ws.append(headers)
    for r in rows:
        ws.append([r.get(k) for k in keys])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
