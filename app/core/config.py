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
ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "change-me-to-a-random-32-byte-hex-string-in-production")
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-to-a-random-secret-key")
SESSION_LIFETIME_DAYS: int = 7
BCRYPT_ROUNDS: int = 12
IS_PRODUCTION: bool = os.getenv("IS_PRODUCTION", "false").lower() in ("1", "true", "yes")

# ---- HH defaults ----
HH_API_URL: str = os.getenv("HH_API_URL", "https://api.hh.ru/resumes")
HH_HOST: str = os.getenv("HH_HOST", "rabota.by")

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
HH_USER_AGENT: str = os.getenv("HH_USER_AGENT", "")
HH_REDIRECT_URI: str = os.getenv("HH_REDIRECT_URI", "")
