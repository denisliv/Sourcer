"""Shared fixtures for tests: async SQLite engine, test client, seed data."""

import asyncio
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

# Register UUID adapter for SQLite
sqlite3.register_adapter(uuid.UUID, lambda u: str(u))

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, String, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import generate_session_token, hash_password, session_expires_at

# Ensure all models are imported so metadata is populated
import app.models  # noqa: F401

from app.models.user import User
from app.models.session import Session

# Override PostgreSQL-specific column types for SQLite compatibility
for table in Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, JSONB):
            column.type = JSON()
        if isinstance(column.type, PG_UUID):
            column.type = String(36)

# Use in-memory SQLite for tests (no PostgreSQL required)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)

TestSessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Provide a clean DB session for each test."""
    async with TestSessionFactory() as session:
        yield session


async def _override_get_db():
    async with TestSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
def client():
    """Synchronous TestClient with DB override (including lifespan)."""
    import app.core.database as db_mod
    import app.main as main_mod

    # Patch async_session_factory globally so lifespan uses test DB
    original_factory = db_mod.async_session_factory
    db_mod.async_session_factory = TestSessionFactory
    main_mod.async_session_factory = TestSessionFactory

    from app.main import app
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    db_mod.async_session_factory = original_factory
    main_mod.async_session_factory = original_factory


@pytest_asyncio.fixture
async def async_client():
    """Async HTTPX client with DB override."""
    import app.core.database as db_mod
    import app.main as main_mod

    original_factory = db_mod.async_session_factory
    db_mod.async_session_factory = TestSessionFactory
    main_mod.async_session_factory = TestSessionFactory

    from app.main import app
    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    db_mod.async_session_factory = original_factory
    main_mod.async_session_factory = original_factory


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create an admin user."""
    user = User(
        email="admin@test.com",
        password_hash=hash_password("admin123"),
        full_name="Test Admin",
        is_admin=True,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession) -> User:
    """Create a regular user."""
    user = User(
        email="user@test.com",
        password_hash=hash_password("user1234"),
        full_name="Test User",
        is_admin=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_session_token(db_session: AsyncSession, admin_user: User) -> str:
    """Create a valid session token for admin user."""
    token = generate_session_token()
    sess = Session(
        user_id=admin_user.id,
        token=token,
        expires_at=session_expires_at(),
    )
    db_session.add(sess)
    await db_session.commit()
    return token


@pytest_asyncio.fixture
async def user_session_token(db_session: AsyncSession, regular_user: User) -> str:
    """Create a valid session token for regular user."""
    token = generate_session_token()
    sess = Session(
        user_id=regular_user.id,
        token=token,
        expires_at=session_expires_at(),
    )
    db_session.add(sess)
    await db_session.commit()
    return token
