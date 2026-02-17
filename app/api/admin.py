"""Admin routes: create/delete users, list users, admin page."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.api.dependencies import require_admin
from app.services.audit import log_action

router = APIRouter(tags=["admin"])


class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    is_admin: bool = False


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str | None
    is_admin: bool
    must_change_password: bool
    created_at: str

    class Config:
        from_attributes = True


@router.post("/api/admin/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only)."""
    # Check uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Пользователь с email {body.email} уже существует",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        is_admin=body.is_admin,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()

    await log_action(db, "admin_create_user", request=request, user_id=admin.id, details={"created_email": body.email})

    return UserOut(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


@router.get("/api/admin/users", response_model=list[UserOut])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)."""
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        UserOut(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            is_admin=u.is_admin,
            must_change_password=u.must_change_password,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in users
    ]


@router.delete("/api/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user by ID (admin only). Cannot delete yourself."""
    if str(admin.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя удалить самого себя",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    await log_action(db, "admin_delete_user", request=request, user_id=admin.id, details={"deleted_email": user.email})
    await db.delete(user)
    await db.flush()
