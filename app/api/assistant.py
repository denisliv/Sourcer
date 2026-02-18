"""AlfaHRAssistent API — chat endpoints with LLM streaming."""

from __future__ import annotations

import json
import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.core.database import async_session_factory, get_db
from app.models.assistant import AssistantChat, AssistantMessage
from app.models.user import User
from app.services.assistant_service import chat_completion_stream, generate_chat_title

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)


# ── Chats CRUD ──────────────────────────────────────────────────────


@router.get("/chats")
async def list_chats(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return user's chat list (recent first)."""
    offset = (page - 1) * per_page
    result = await db.execute(
        select(AssistantChat)
        .where(AssistantChat.user_id == user.id)
        .order_by(AssistantChat.updated_at.desc())
        .limit(per_page)
        .offset(offset)
    )
    chats = result.scalars().all()
    count_row = await db.execute(
        select(func.count()).select_from(AssistantChat).where(AssistantChat.user_id == user.id)
    )
    total = count_row.scalar() or 0
    return {
        "items": [
            {
                "id": str(c.id),
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in chats
        ],
        "total": total,
    }


@router.post("/chats")
async def create_chat(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty chat and return its id."""
    chat = AssistantChat(user_id=user.id, title="Новый чат")
    db.add(chat)
    await db.flush()
    return {"id": str(chat.id), "title": chat.title}


class RenameChatRequest(BaseModel):
    title: str


@router.patch("/chats/{chat_id}")
async def rename_chat(
    chat_id: str,
    body: RenameChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename an existing chat."""
    try:
        cid = _uuid.UUID(chat_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Недействительный ID"})
    chat = await db.get(AssistantChat, cid)
    if chat is None or chat.user_id != user.id:
        return JSONResponse(status_code=404, content={"error": "Чат не найден"})
    chat.title = body.title[:255]
    return {"ok": True}


@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat and all its messages."""
    try:
        cid = _uuid.UUID(chat_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Недействительный ID"})
    chat = await db.get(AssistantChat, cid)
    if chat is None or chat.user_id != user.id:
        return JSONResponse(status_code=404, content={"error": "Чат не найден"})
    await db.delete(chat)
    await db.commit()
    return {"ok": True}


# ── Messages ────────────────────────────────────────────────────────


@router.get("/chats/{chat_id}/messages")
async def get_messages(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all messages in a chat."""
    try:
        cid = _uuid.UUID(chat_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Недействительный ID"})

    result = await db.execute(
        select(AssistantChat)
        .where(AssistantChat.id == cid, AssistantChat.user_id == user.id)
        .options(selectinload(AssistantChat.messages))
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        return JSONResponse(status_code=404, content={"error": "Чат не найден"})

    return {
        "chat_id": str(chat.id),
        "title": chat.title,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in chat.messages
        ],
    }


class SendMessageRequest(BaseModel):
    content: str


@router.post("/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept user message, stream LLM response via SSE, persist both messages."""
    content = body.content.strip()
    if not content:
        return JSONResponse(status_code=400, content={"error": "Сообщение не может быть пустым"})

    try:
        cid = _uuid.UUID(chat_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Недействительный ID"})

    result = await db.execute(
        select(AssistantChat)
        .where(AssistantChat.id == cid, AssistantChat.user_id == user.id)
        .options(selectinload(AssistantChat.messages))
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        return JSONResponse(status_code=404, content={"error": "Чат не найден"})

    is_first_message = len(chat.messages) == 0

    user_msg = AssistantMessage(chat_id=chat.id, role="user", content=content)
    db.add(user_msg)
    await db.flush()

    history = [
        {"role": m.role, "content": m.content}
        for m in chat.messages
        if m.role in ("user", "assistant")
    ]
    history.append({"role": "user", "content": content})

    user_id = user.id
    chat_id_uuid = chat.id
    await db.commit()

    async def event_stream():
        full_response = ""
        try:
            async for token in chat_completion_stream(history):
                full_response += token
                data = json.dumps({"token": token}, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as exc:
            logger.exception("LLM stream error")
            error_data = json.dumps({"error": str(exc)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
            full_response = ""

        async with async_session_factory() as save_db:
            try:
                if full_response:
                    assistant_msg = AssistantMessage(
                        chat_id=chat_id_uuid, role="assistant", content=full_response
                    )
                    save_db.add(assistant_msg)

                    chat_obj = await save_db.get(AssistantChat, chat_id_uuid)
                    if chat_obj:
                        from datetime import datetime, timezone
                        chat_obj.updated_at = datetime.now(timezone.utc)

                    await save_db.commit()

                if is_first_message and full_response:
                    title = await generate_chat_title(content)
                    chat_obj = await save_db.get(AssistantChat, chat_id_uuid)
                    if chat_obj and chat_obj.title == "Новый чат":
                        chat_obj.title = title
                        await save_db.commit()
                        title_data = json.dumps({"title": title}, ensure_ascii=False)
                        yield f"data: {title_data}\n\n"
            except Exception:
                logger.exception("Failed to save assistant message")

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
