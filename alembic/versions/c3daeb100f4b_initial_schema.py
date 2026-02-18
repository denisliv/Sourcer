"""initial_schema

Revision ID: c3daeb100f4b
Create Date: 2026-02-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3daeb100f4b"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    )

    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(255), unique=True, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_sessions_token", "sessions", ["token"])
    op.create_index("idx_sessions_expires", "sessions", ["expires_at"])

    # --- credentials ---
    op.create_table(
        "credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("encrypted_data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_credentials_user_provider"),
    )

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "idx_audit_user_created", "audit_logs", ["user_id", sa.text("created_at DESC")]
    )

    # --- searches ---
    op.create_table(
        "searches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.String(500), nullable=True),
        sa.Column("query_params", postgresql.JSONB(), nullable=True),
        sa.Column("sources", sa.String(20), server_default="hh", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("total_results", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_searches_user", "searches", ["user_id", sa.text("created_at DESC")]
    )

    # --- candidates ---
    op.create_table(
        "candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "search_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("searches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("current_title", sa.String(500), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("profile_url", sa.String(1000), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "search_id", "source", "external_id", name="uq_candidates_search_source_ext"
        ),
    )
    op.create_index("idx_candidates_search", "candidates", ["search_id"])

    # --- benchmark_searches ---
    op.create_table(
        "benchmark_searches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.String(500), nullable=False),
        sa.Column("query_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("total_vacancies", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filtered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stat_min", sa.Float(), nullable=True),
        sa.Column("stat_max", sa.Float(), nullable=True),
        sa.Column("stat_mean", sa.Float(), nullable=True),
        sa.Column("stat_median", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="completed", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    )
    op.create_index(
        op.f("ix_benchmark_searches_user_id"),
        "benchmark_searches",
        ["user_id"],
        unique=False,
    )

    # --- assistant_chats ---
    op.create_table(
        "assistant_chats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assistant_chats_user_id"),
        "assistant_chats",
        ["user_id"],
        unique=False,
    )

    # --- assistant_messages ---
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["assistant_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assistant_messages_chat_id"),
        "assistant_messages",
        ["chat_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assistant_messages_chat_id"), table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index(op.f("ix_assistant_chats_user_id"), table_name="assistant_chats")
    op.drop_table("assistant_chats")
    op.drop_index(op.f("ix_benchmark_searches_user_id"), table_name="benchmark_searches")
    op.drop_table("benchmark_searches")
    op.drop_table("candidates")
    op.drop_table("searches")
    op.drop_table("audit_logs")
    op.drop_table("credentials")
    op.drop_table("sessions")
    op.drop_table("users")
