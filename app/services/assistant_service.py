"""AlfaHRAssistent — LLM chat service via OpenAI-compatible API."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.core.config import ASSISTANT_SYSTEM_PROMPT, OPENAI_API_BASE, OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)
    return _client


async def chat_completion_stream(
    history: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    """Stream assistant response token-by-token.

    `history` is a list of {"role": ..., "content": ...} dicts
    (user / assistant turns only; system prompt is prepended automatically).
    """
    messages = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}, *history]

    client = _get_client()
    stream = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=4096,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def generate_chat_title(user_message: str) -> str:
    """Ask LLM to produce a short title (<=6 words) for a chat based on the first message."""
    client = _get_client()
    try:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Придумай очень короткое название (максимум 6 слов) для HR-чата, "
                        "начинающегося с приведённого сообщения. "
                        "Отвечай ТОЛЬКО названием, без кавычек и пояснений."
                    ),
                },
                {"role": "user", "content": user_message[:500]},
            ],
            temperature=0.5,
            max_tokens=30,
        )
        title = resp.choices[0].message.content.strip().strip('"\'')
        return title[:255] if title else "Новый чат"
    except Exception:
        logger.exception("Failed to generate chat title")
        return "Новый чат"
