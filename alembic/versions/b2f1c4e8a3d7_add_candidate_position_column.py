"""extract_extra_data_add_position

Revision ID: b2f1c4e8a3d7
Revises: 9aa78e7cbe64
Create Date: 2026-03-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2f1c4e8a3d7'
down_revision: Union[str, Sequence[str], None] = '9aa78e7cbe64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('photo', sa.String(1000), nullable=True))
    op.add_column('candidates', sa.Column('experience', sa.String(100), nullable=True))
    op.add_column('candidates', sa.Column('last_work', sa.String(500), nullable=True))
    op.add_column('candidates', sa.Column('salary', sa.String(100), nullable=True))
    op.add_column('candidates', sa.Column('resume_updated_at', sa.String(100), nullable=True))
    op.add_column('candidates', sa.Column('position', sa.Integer(), nullable=True))

    op.execute("""
        UPDATE candidates SET
            photo = extra_data->>'photo',
            experience = extra_data->>'experience',
            last_work = extra_data->>'last_work',
            salary = extra_data->>'salary',
            resume_updated_at = extra_data->>'updated_at'
        WHERE extra_data IS NOT NULL
    """)

    op.drop_column('candidates', 'extra_data')


def downgrade() -> None:
    op.add_column('candidates', sa.Column('extra_data', sa.JSON(), nullable=True))

    op.execute("""
        UPDATE candidates SET extra_data = jsonb_build_object(
            'photo', photo,
            'experience', experience,
            'last_work', last_work,
            'salary', salary,
            'updated_at', resume_updated_at
        )
    """)

    op.drop_column('candidates', 'position')
    op.drop_column('candidates', 'resume_updated_at')
    op.drop_column('candidates', 'salary')
    op.drop_column('candidates', 'last_work')
    op.drop_column('candidates', 'experience')
    op.drop_column('candidates', 'photo')
