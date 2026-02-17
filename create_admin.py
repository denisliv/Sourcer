"""CLI script to create the initial admin user.

Usage:
    python create_admin.py admin@example.com mypassword "Admin Name"
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.core.database import Base
from app.core.security import hash_password
from app.models.user import User

# Ensure all models are loaded
import app.models  # noqa: F401


async def create_admin(email: str, password: str, full_name: str | None = None):
    # Create tables if they don't exist (for local dev without Alembic)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # Check if already exists
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            print(f"User {email} already exists.")
            return

        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            is_admin=True,
            must_change_password=False,
        )
        db.add(user)
        await db.commit()
        print(f"Admin user created: {email}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python create_admin.py <email> <password> [full_name]")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else None

    asyncio.run(create_admin(email, password, name))
