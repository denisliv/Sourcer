"""Reference data loaded from config/constants.yaml."""

import yaml

from app.core.config import BASE_DIR

_YAML_PATH = BASE_DIR / "config" / "constants.yaml"

with open(_YAML_PATH, encoding="utf-8") as f:
    _data = yaml.safe_load(f)

# ---- HH Areas (grouped by country) ----
HH_AREA_GROUPS: list[dict] = _data["hh_area_groups"]

HH_AREAS: list[tuple[int, str]] = []
HH_AREAS_DICT: dict[int, str] = {}
HH_AREA_HOST_MAP: dict[int, str] = {}

for _group in HH_AREA_GROUPS:
    _host = _group["host"]
    for _area_id, _area_name in _group["areas"]:
        HH_AREAS.append((_area_id, _area_name))
        HH_AREAS_DICT[_area_id] = _area_name
        HH_AREA_HOST_MAP[_area_id] = _host

HH_DEFAULT_AREA: int = 16

# ---- Benchmark ----
BENCHMARK_AREAS: dict[str, str] = _data["benchmark_areas"]
BENCHMARK_EXPERIENCE_OPTIONS: dict[str, str | None] = _data["benchmark_experience_options"]
BENCHMARK_PERIOD_OPTIONS: list[int] = _data["benchmark_period_options"]
BENCHMARK_INDUSTRIES: dict[str, str] = _data["benchmark_industries"]
