"""add candidate_views table

Revision ID: 10a5349774d9
Revises: c3daeb100f4b
Create Date: 2026-02-26 18:53:18.492413

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '10a5349774d9'
down_revision: Union[str, Sequence[str], None] = 'c3daeb100f4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('candidate_views',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'source', 'external_id', name='uq_candidate_views_user_source_ext'),
    )
    op.create_index(op.f('ix_candidate_views_user_id'), 'candidate_views', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_candidate_views_user_id'), table_name='candidate_views')
    op.drop_table('candidate_views')
