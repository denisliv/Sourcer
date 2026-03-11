"""Tests for assistant endpoints: chat CRUD and messages."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantChat, AssistantMessage
from app.models.user import User


@pytest_asyncio.fixture
async def user_chat(db_session: AsyncSession, regular_user: User) -> AssistantChat:
    """Create a chat for the regular user."""
    chat = AssistantChat(user_id=regular_user.id, title="Test Chat")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


@pytest_asyncio.fixture
async def chat_with_messages(
    db_session: AsyncSession, user_chat: AssistantChat,
) -> AssistantChat:
    """Create a chat with messages."""
    db_session.add(AssistantMessage(
        chat_id=user_chat.id, role="user", content="Hello"
    ))
    db_session.add(AssistantMessage(
        chat_id=user_chat.id, role="assistant", content="Hi! How can I help?"
    ))
    await db_session.commit()
    return user_chat


class TestListChats:
    def test_unauthenticated(self, client):
        resp = client.get(
            "/api/assistant/chats",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_empty_list(self, async_client, regular_user, user_session_token):
        resp = await async_client.get(
            "/api/assistant/chats",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_with_chats(
        self, async_client, user_chat, user_session_token,
    ):
        resp = await async_client.get(
            "/api/assistant/chats",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Test Chat"

    async def test_list_pagination(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        for i in range(5):
            db_session.add(AssistantChat(
                user_id=regular_user.id, title=f"Chat {i}"
            ))
        await db_session.commit()

        resp = await async_client.get(
            "/api/assistant/chats?page=1&per_page=2",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5


class TestCreateChat:
    def test_unauthenticated(self, client):
        resp = client.post(
            "/api/assistant/chats",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_create_chat(self, client, user_session_token):
        resp = client.post(
            "/api/assistant/chats",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["title"] == "Новый чат"


class TestRenameChat:
    def test_unauthenticated(self, client):
        resp = client.patch(
            f"/api/assistant/chats/{uuid.uuid4()}",
            json={"title": "New Title"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_id(self, async_client, user_session_token):
        resp = await async_client.patch(
            "/api/assistant/chats/bad-id",
            json={"title": "New Title"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    async def test_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.patch(
            f"/api/assistant/chats/{uuid.uuid4()}",
            json={"title": "New Title"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 404

    async def test_rename_success(
        self, async_client, user_chat, user_session_token,
    ):
        resp = await async_client.patch(
            f"/api/assistant/chats/{user_chat.id}",
            json={"title": "Renamed Chat"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_other_user_cannot_rename(
        self, async_client, user_chat, admin_session_token,
    ):
        resp = await async_client.patch(
            f"/api/assistant/chats/{user_chat.id}",
            json={"title": "Hacked"},
            cookies={"session_token": admin_session_token},
        )
        assert resp.status_code == 404


class TestDeleteChat:
    def test_unauthenticated(self, client):
        resp = client.delete(
            f"/api/assistant/chats/{uuid.uuid4()}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_id(self, async_client, user_session_token):
        resp = await async_client.delete(
            "/api/assistant/chats/bad-id",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    async def test_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.delete(
            f"/api/assistant/chats/{uuid.uuid4()}",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 404

    async def test_delete_success(
        self, async_client, user_chat, user_session_token,
    ):
        resp = await async_client.delete(
            f"/api/assistant/chats/{user_chat.id}",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_other_user_cannot_delete(
        self, async_client, user_chat, admin_session_token,
    ):
        resp = await async_client.delete(
            f"/api/assistant/chats/{user_chat.id}",
            cookies={"session_token": admin_session_token},
        )
        assert resp.status_code == 404


class TestGetMessages:
    def test_unauthenticated(self, client):
        resp = client.get(
            f"/api/assistant/chats/{uuid.uuid4()}/messages",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_invalid_id(self, async_client, user_session_token):
        resp = await async_client.get(
            "/api/assistant/chats/bad-id/messages",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    async def test_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.get(
            f"/api/assistant/chats/{uuid.uuid4()}/messages",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 404

    async def test_empty_chat(
        self, async_client, user_chat, user_session_token,
    ):
        resp = await async_client.get(
            f"/api/assistant/chats/{user_chat.id}/messages",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []
        assert data["title"] == "Test Chat"

    async def test_chat_with_messages(
        self, async_client, chat_with_messages, user_session_token,
    ):
        resp = await async_client.get(
            f"/api/assistant/chats/{chat_with_messages.id}/messages",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"


class TestSendMessage:
    def test_unauthenticated(self, client):
        resp = client.post(
            f"/api/assistant/chats/{uuid.uuid4()}/messages",
            json={"content": "Hello"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    async def test_empty_content(
        self, async_client, user_chat, user_session_token,
    ):
        resp = await async_client.post(
            f"/api/assistant/chats/{user_chat.id}/messages",
            json={"content": "  "},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    async def test_invalid_chat_id(self, async_client, user_session_token):
        resp = await async_client.post(
            "/api/assistant/chats/bad-id/messages",
            json={"content": "Hello"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    async def test_chat_not_found(self, async_client, regular_user, user_session_token):
        resp = await async_client.post(
            f"/api/assistant/chats/{uuid.uuid4()}/messages",
            json={"content": "Hello"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 404

    async def test_send_message_returns_sse(
        self, async_client, user_chat, user_session_token,
    ):
        async def mock_stream(history):
            yield "Hello "
            yield "world!"

        with patch(
            "app.api.assistant.chat_completion_stream",
            side_effect=mock_stream,
        ), patch(
            "app.api.assistant.generate_chat_title",
            new_callable=AsyncMock,
            return_value="Test Title",
        ):
            resp = await async_client.post(
                f"/api/assistant/chats/{user_chat.id}/messages",
                json={"content": "Hi there"},
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            body = resp.text
            assert "Hello " in body or "world!" in body or "[DONE]" in body
