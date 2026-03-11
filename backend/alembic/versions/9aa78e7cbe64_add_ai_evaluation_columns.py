"""add_ai_evaluation_columns

Revision ID: 9aa78e7cbe64
Revises: 10a5349774d9
Create Date: 2026-03-02 13:40:08.707865

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '9aa78e7cbe64'
down_revision: Union[str, Sequence[str], None] = '10a5349774d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('candidates', sa.Column('ai_score', sa.Integer(), nullable=True))
    op.add_column('candidates', sa.Column('ai_summary', sa.Text(), nullable=True))
    op.add_column('candidates', sa.Column('ai_status', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('candidates', 'ai_status')
    op.drop_column('candidates', 'ai_summary')
    op.drop_column('candidates', 'ai_score')
    op.drop_column('candidates', 'raw_data')
