"""LLM system prompts loaded from config/prompts.yaml."""

import yaml

from app.core.config import BASE_DIR

_YAML_PATH = BASE_DIR / "config" / "prompts.yaml"

with open(_YAML_PATH, encoding="utf-8") as f:
    _data = yaml.safe_load(f)

EVALUATION_SYSTEM_PROMPT: str = _data["evaluation_system_prompt"].strip()
ASSISTANT_SYSTEM_PROMPT: str = _data["assistant_system_prompt"].strip()
