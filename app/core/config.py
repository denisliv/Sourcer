"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Sourcer/

load_dotenv(BASE_DIR / ".env")

# ---- Database ----
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://admin:admin@localhost:5432/hrservice"
)

# ---- Security ----
ENCRYPTION_KEY: str = os.getenv(
    "ENCRYPTION_KEY", "change-me-to-a-random-32-byte-hex-string-in-production"
)
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-to-a-random-secret-key")
SESSION_LIFETIME_DAYS: int = 7
BCRYPT_ROUNDS: int = 12
IS_PRODUCTION: bool = os.getenv("IS_PRODUCTION", "false").lower() in (
    "1",
    "true",
    "yes",
)

# ---- HH defaults ----
HH_API_URL: str = "https://api.hh.ru/resumes"
HH_HOST: str = "rabota.by"

# ---- HH Areas (Belarus regions) ----
HH_AREAS: list[tuple[int, str]] = [
    (16, "Беларусь"),
    (1007, "Брест"),
    (2233, "Брестская область"),
    (1005, "Витебск"),
    (2234, "Витебская область"),
    (1003, "Гомель"),
    (2235, "Гомельская область"),
    (1006, "Гродно"),
    (2236, "Гродненская область"),
    (1002, "Минск"),
    (2237, "Минская область"),
    (1004, "Могилев"),
    (2238, "Могилевская область"),
]
HH_AREAS_DICT: dict[int, str] = dict(HH_AREAS)
HH_DEFAULT_AREA: int = HH_AREAS[0][0]  # 16 — Беларусь

# ---- HH OAuth ----
HH_CLIENT_ID: str = os.getenv("HH_APP_CLIENT_ID", "")
HH_CLIENT_SECRET: str = os.getenv("HH_APP_CLIENT_SECRET", "")
HH_APP_TOKEN: str = os.getenv("HH_APP_TOKEN", "")
HH_USER_AGENT: str = os.getenv("HH_USER_AGENT", "")
HH_REDIRECT_URI: str = os.getenv("HH_REDIRECT_URI", "")

# ---- Benchmark defaults ----
BENCHMARK_AREAS: dict[str, str] = {
    "16": "Беларусь",
    "1": "Москва",
    "2": "Санкт-Петербург",
    "all": "Все регионы",
}
BENCHMARK_EXPERIENCE_OPTIONS: dict[str, str | None] = {
    "": None,
    "noExperience": "Нет опыта",
    "between1And3": "От 1 года до 3 лет",
    "between3And6": "От 3 до 6 лет",
    "moreThan6": "Более 6 лет",
}
BENCHMARK_PERIOD_OPTIONS: list[int] = [1, 7, 14, 30, 60, 90, 180, 365]

# ---- OpenAI / LLM ----
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

ASSISTANT_SYSTEM_PROMPT: str = (
    "Ты — AlfaHRAssistent, интеллектуальный HR-ассистент компании. "
    "Ты призван помогать HR-специалистам в их повседневной работе: "
    "составление описаний вакансий, подготовка вопросов для интервью, "
    "анализ резюме, консультации по трудовому законодательству, "
    "помощь в адаптации новых сотрудников, разработка HR-политик и процедур, "
    "подготовка отчётов и аналитики по персоналу. "
    "Отвечай профессионально, структурированно и по делу. "
    "Используй маркированные списки и форматирование для удобства чтения. "
    "Если вопрос выходит за рамки HR-тематики, вежливо сообщи об этом и "
    "предложи переформулировать запрос."
)
