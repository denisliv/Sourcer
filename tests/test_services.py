"""Unit tests for services: evaluation, assistant, search, hh_oauth."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.evaluation_service import (
    _format_date,
    _format_experience_months,
    _strip_html,
    prepare_candidate_context,
)
from app.services.hh_oauth import compute_expires_at, is_token_expired
from app.services.search_service import normalize_sources


# ── normalize_sources ──────────────────────────────────────────────

class TestNormalizeSources:
    def test_hh_only(self):
        assert normalize_sources("hh") == (True, False)

    def test_linkedin_only(self):
        assert normalize_sources("linkedin") == (False, True)

    def test_both(self):
        assert normalize_sources("both") == (True, True)

    def test_empty_defaults_to_both(self):
        assert normalize_sources("") == (True, True)

    def test_case_insensitive(self):
        assert normalize_sources("BOTH") == (True, True)
        assert normalize_sources("HH") == (True, False)
        assert normalize_sources("LinkedIn") == (False, True)

    def test_none_defaults_to_both(self):
        assert normalize_sources(None) == (True, True)


# ── evaluation_service helpers ─────────────────────────────────────

class TestFormatDate:
    def test_none(self):
        assert _format_date(None) == ""

    def test_empty(self):
        assert _format_date("") == ""

    def test_full_date(self):
        result = _format_date("2024-03-15")
        assert "2024" in result
        assert "мар" in result

    def test_year_only(self):
        assert _format_date("2024") == "2024"

    def test_invalid(self):
        assert _format_date("not-a-date") == "not-a-date"


class TestFormatExperienceMonths:
    def test_none(self):
        assert _format_experience_months(None) == "—"

    def test_zero(self):
        assert _format_experience_months(0) == "< 1 мес."

    def test_months(self):
        assert "мес." in _format_experience_months(5)

    def test_years(self):
        assert "г." in _format_experience_months(24)

    def test_years_and_months(self):
        result = _format_experience_months(26)
        assert "г." in result
        assert "мес." in result


class TestStripHtml:
    def test_plain_text(self):
        assert _strip_html("hello") == "hello"

    def test_html_tags(self):
        assert _strip_html("<p>hello</p>") == "hello"

    def test_br_tags(self):
        assert "\n" in _strip_html("line1<br/>line2")

    def test_whitespace(self):
        result = _strip_html("  lots   of   spaces  ")
        assert "lots of spaces" == result


class TestPrepareCandidateContext:
    def test_minimal(self):
        result = prepare_candidate_context({})
        assert "Резюме: —" in result

    def test_with_title(self):
        result = prepare_candidate_context({"title": "Python Developer"})
        assert "Python Developer" in result

    def test_with_experience(self):
        data = {
            "title": "Dev",
            "experience": [{
                "company": "ACME",
                "position": "Developer",
                "start": "2020-01",
                "end": "2024-01",
            }],
        }
        result = prepare_candidate_context(data)
        assert "ACME" in result
        assert "Developer" in result

    def test_with_skills(self):
        data = {
            "title": "Dev",
            "skill_set": ["Python", "FastAPI", "Docker"],
        }
        result = prepare_candidate_context(data)
        assert "Python" in result
        assert "FastAPI" in result

    def test_with_education(self):
        data = {
            "title": "Dev",
            "education": {
                "level": {"name": "Высшее"},
                "primary": [{"name": "MIT", "year": 2020}],
            },
        }
        result = prepare_candidate_context(data)
        assert "Высшее" in result
        assert "MIT" in result

    def test_with_languages(self):
        data = {
            "title": "Dev",
            "language": [
                {"name": "English", "level": {"name": "B2"}},
                {"name": "Russian", "level": {"name": "Native"}},
            ],
        }
        result = prepare_candidate_context(data)
        assert "English" in result
        assert "Russian" in result


# ── evaluation_service evaluate_candidate ──────────────────────────

class TestEvaluateCandidate:
    @pytest.fixture(autouse=True)
    def setup_semaphore(self):
        from app.services.evaluation_service import init_semaphore
        init_semaphore(5)

    async def test_successful_evaluation(self):
        from app.services.evaluation_service import evaluate_candidate

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"score": 8, "summary": "Good match"}'))
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.evaluation_service._get_client", return_value=mock_client):
            result = await evaluate_candidate("Python dev needed", "Knows Python well")
            assert result["score"] == 8
            assert result["summary"] == "Good match"

    async def test_invalid_llm_response(self):
        from app.services.evaluation_service import evaluate_candidate

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="not json"))
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.evaluation_service._get_client", return_value=mock_client):
            result = await evaluate_candidate("Python dev", "Some context")
            assert result["score"] is None

    async def test_api_error(self):
        from app.services.evaluation_service import evaluate_candidate

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))

        with patch("app.services.evaluation_service._get_client", return_value=mock_client):
            result = await evaluate_candidate("Python dev", "Context")
            assert result["score"] is None
            assert "Ошибка" in result["summary"]


# ── assistant_service ──────────────────────────────────────────────

class TestAssistantService:
    async def test_chat_completion_stream(self):
        from app.services.assistant_service import chat_completion_stream

        mock_chunk_1 = MagicMock()
        mock_chunk_1.choices = [MagicMock(delta=MagicMock(content="Hello"))]
        mock_chunk_2 = MagicMock()
        mock_chunk_2.choices = [MagicMock(delta=MagicMock(content=" world"))]

        async def mock_aiter(*args):
            yield mock_chunk_1
            yield mock_chunk_2

        mock_stream = MagicMock()
        mock_stream.__aiter__ = mock_aiter

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        with patch("app.services.assistant_service._get_client", return_value=mock_client):
            tokens = []
            async for token in chat_completion_stream([{"role": "user", "content": "Hi"}]):
                tokens.append(token)
            assert tokens == ["Hello", " world"]

    async def test_generate_chat_title(self):
        from app.services.assistant_service import generate_chat_title

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="HR вопрос о найме"))
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.assistant_service._get_client", return_value=mock_client):
            title = await generate_chat_title("How to hire a Python developer?")
            assert title == "HR вопрос о найме"

    async def test_generate_chat_title_on_error(self):
        from app.services.assistant_service import generate_chat_title

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

        with patch("app.services.assistant_service._get_client", return_value=mock_client):
            title = await generate_chat_title("Test message")
            assert title == "Новый чат"


# ── hh_oauth helpers ──────────────────────────────────────────────

class TestHHOAuthHelpers:
    def test_compute_expires_at(self):
        result = compute_expires_at(3600)
        assert "T" in result  # ISO format
        from datetime import datetime
        dt = datetime.fromisoformat(result)
        assert dt is not None

    def test_is_token_expired_none(self):
        assert is_token_expired(None) is True

    def test_is_token_expired_empty(self):
        assert is_token_expired("") is True

    def test_is_token_expired_future(self):
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert is_token_expired(future) is False

    def test_is_token_expired_past(self):
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert is_token_expired(past) is True

    def test_is_token_expired_with_buffer(self):
        from datetime import datetime, timedelta, timezone
        almost_expired = (datetime.now(timezone.utc) + timedelta(seconds=100)).isoformat()
        assert is_token_expired(almost_expired, buffer_seconds=300) is True

    def test_is_token_expired_invalid_format(self):
        assert is_token_expired("not-a-date") is True


class TestExchangeCodeForTokens:
    async def test_exchange_success(self):
        from app.services.hh_oauth import exchange_code_for_tokens

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "test_access",
            "refresh_token": "test_refresh",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.hh_oauth.httpx.AsyncClient", return_value=mock_client):
            result = await exchange_code_for_tokens("test_code")
            assert result["access_token"] == "test_access"
            assert result["refresh_token"] == "test_refresh"


# ── audit service ────────────────────────────────────────────────

class TestAuditService:
    async def test_log_action(self):
        from app.services.audit import log_action
        import uuid

        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        await log_action(
            mock_db,
            "test_action",
            request=None,
            user_id=uuid.uuid4(),
            details={"key": "value"},
        )
        mock_db.add.assert_called_once()

    async def test_log_action_with_request(self):
        from app.services.audit import log_action
        import uuid

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        await log_action(
            mock_db,
            "login",
            request=mock_request,
            user_id=uuid.uuid4(),
        )
        mock_db.add.assert_called_once()
