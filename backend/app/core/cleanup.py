"""Periodic data cleanup: stale searches, old candidate views, expired sessions."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.candidate_view import CandidateView
from app.models.search import Search as SearchModel
from app.models.session import Session as SessionModel

logger = logging.getLogger(__name__)


async def run_cleanup() -> None:
    """Delete stale searches (with cascaded candidates) and old candidate views."""
    now = datetime.now(timezone.utc)
    search_cutoff = now - timedelta(days=settings.search_ttl_days)
    view_cutoff = now - timedelta(days=settings.candidate_view_ttl_days)

    async with async_session_factory() as db:
        res_searches = await db.execute(
            delete(SearchModel).where(SearchModel.created_at < search_cutoff)
        )
        res_views = await db.execute(
            delete(CandidateView).where(CandidateView.viewed_at < view_cutoff)
        )
        await db.execute(
            delete(SessionModel).where(SessionModel.expires_at < now)
        )
        await db.commit()

    logger.info(
        "Cleanup: deleted %d searches (with candidates), %d candidate views",
        res_searches.rowcount,
        res_views.rowcount,
    )


async def periodic_cleanup() -> None:
    """Background loop that runs cleanup every CLEANUP_INTERVAL_HOURS."""
    interval = settings.cleanup_interval_hours * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            await run_cleanup()
        except Exception:
            logger.exception("Periodic cleanup failed")
