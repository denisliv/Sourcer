"""Reference data loaded from config/constants.yaml."""

import yaml

from app.core.config import BASE_DIR

_YAML_PATH = BASE_DIR / "config" / "constants.yaml"

with open(_YAML_PATH, encoding="utf-8") as f:
    _data = yaml.safe_load(f)

# ---- HH Areas (Belarus regions) ----
HH_AREAS: list[tuple[int, str]] = [tuple(item) for item in _data["hh_areas"]]
HH_AREAS_DICT: dict[int, str] = dict(HH_AREAS)
HH_DEFAULT_AREA: int = HH_AREAS[0][0]  # 16 — Беларусь

# ---- Benchmark ----
BENCHMARK_AREAS: dict[str, str] = _data["benchmark_areas"]
BENCHMARK_EXPERIENCE_OPTIONS: dict[str, str | None] = _data["benchmark_experience_options"]
BENCHMARK_PERIOD_OPTIONS: list[int] = _data["benchmark_period_options"]
BENCHMARK_INDUSTRIES: dict[str, str] = _data["benchmark_industries"]
