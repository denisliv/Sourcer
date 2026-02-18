import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BenchmarkSearch(Base):
    __tablename__ = "benchmark_searches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(String(500), nullable=False)
    query_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_vacancies: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filtered_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stat_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed", server_default="completed"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="benchmark_searches")
