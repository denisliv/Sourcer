"""Tests for search API endpoints: search, history, results, evaluate, export."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.search import Search
from app.models.user import User


@pytest_asyncio.fixture
async def search_with_candidates(db_session: AsyncSession, regular_user: User):
    """Create a search record with candidates for testing."""
    search = Search(
        user_id=regular_user.id,
        query_text="Python Developer",
        sources="hh",
        status="done",
        total_results=2,
    )
    db_session.add(search)
    await db_session.flush()

    for i in range(2):
        db_session.add(Candidate(
            search_id=search.id,
            source="hh",
            external_id=f"ext_{i}",
            full_name=f"Candidate {i}",
            current_title="Developer",
            location="Minsk",
            profile_url=f"https://hh.ru/resume/{i}",
            position=i,
        ))
    await db_session.commit()
    return search


class TestSearchHistory:
    def test_unauthenticated(self, client):
        resp = client.get(
            "/api/search/history",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_empty_history(self, async_client, regular_user, user_session_token):
        resp = await async_client.get(
            "/api/search/history",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_history_with_results(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        search = Search(
            user_id=regular_user.id,
            query_text="Python",
            sources="hh",
            status="done",
            total_results=5,
        )
        db_session.add(search)
        await db_session.commit()

        resp = await async_client.get(
            "/api/search/history",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["query_text"] == "Python"

    async def test_history_pagination(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        for i in range(5):
            db_session.add(Search(
                user_id=regular_user.id,
                query_text=f"Query {i}",
                sources="hh",
                status="done",
            ))
        await db_session.commit()

        resp = await async_client.get(
            "/api/search/history?page=1&per_page=2",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5


class TestGetSearch:
    def test_unauthenticated(self, client):
        resp = client.get(
            f"/api/search/{uuid.uuid4()}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_id(self, async_client, user_session_token):
        resp = await async_client.get(
            "/api/search/not-a-uuid",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.get(
            f"/api/search/{uuid.uuid4()}",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_get_search_success(
        self, async_client, search_with_candidates, user_session_token,
    ):
        resp = await async_client.get(
            f"/api/search/{search_with_candidates.id}",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is False
        assert data["query_text"] == "Python Developer"


class TestSearchResults:
    def test_unauthenticated(self, client):
        resp = client.get(
            f"/api/search/{uuid.uuid4()}/results",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_id(self, async_client, user_session_token):
        resp = await async_client.get(
            "/api/search/bad-id/results",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.get(
            f"/api/search/{uuid.uuid4()}/results",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_results_success(
        self, async_client, search_with_candidates, user_session_token,
    ):
        resp = await async_client.get(
            f"/api/search/{search_with_candidates.id}/results",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is False
        assert len(data["candidates"]) == 2
        assert data["candidates"][0]["full_name"] == "Candidate 0"


class TestSearchEndpoint:
    def test_unauthenticated(self, client):
        resp = client.get(
            "/api/search?search_text=python",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_empty_query(self, client, user_session_token):
        resp = client.get(
            "/api/search?search_text=&search_skills=&search_company=",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    def test_search_with_mocked_execute(self, client, user_session_token):
        mock_result = {
            "error": False,
            "search_id": str(uuid.uuid4()),
            "total_found": 1,
            "returned": 1,
            "candidates": [{
                "source": "hh",
                "external_id": "123",
                "full_name": "Test User",
                "title": "Dev",
                "area": "Minsk",
                "url": "https://hh.ru/resume/123",
            }],
        }
        with patch(
            "app.api.search.execute_search",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.get(
                "/api/search?search_text=python&sources=hh",
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["error"] is False
            assert data["returned"] == 1


class TestExportCSV:
    def test_unauthenticated(self, client):
        resp = client.get(
            f"/api/export?search_id={uuid.uuid4()}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_id(self, async_client, user_session_token):
        resp = await async_client.get(
            "/api/export?search_id=bad-id",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.get(
            f"/api/export?search_id={uuid.uuid4()}",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_export_success(
        self, async_client, search_with_candidates, user_session_token,
    ):
        resp = await async_client.get(
            f"/api/export?search_id={search_with_candidates.id}",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert len(resp.content) > 0


class TestEvaluateEndpoint:
    def test_unauthenticated(self, client):
        resp = client.post(
            f"/api/search/{uuid.uuid4()}/evaluate",
            json={"job_description": "Python dev"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_search_id(self, async_client, user_session_token):
        resp = await async_client.post(
            "/api/search/bad-id/evaluate",
            json={"job_description": "Python dev"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_empty_job_description(
        self, async_client, search_with_candidates, user_session_token,
    ):
        resp = await async_client.post(
            f"/api/search/{search_with_candidates.id}/evaluate",
            json={"job_description": "  "},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is True

    async def test_no_hh_credentials(
        self, async_client, search_with_candidates, user_session_token,
    ):
        with patch(
            "app.api.search.get_hh_headers",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await async_client.post(
                f"/api/search/{search_with_candidates.id}/evaluate",
                json={"job_description": "Senior Python Developer"},
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 200
            assert resp.json()["error"] is True


class TestCandidateView:
    def test_unauthenticated(self, client):
        resp = client.post(
            "/api/candidate-view",
            json={"source": "hh", "external_id": "123"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401
