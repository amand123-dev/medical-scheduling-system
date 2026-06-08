"""add per-provider availability fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider",
        sa.Column("work_days", sa.String(20), nullable=True),
        schema="operational",
    )
    op.add_column(
        "provider",
        sa.Column("work_start_hour", sa.Integer, nullable=True),
        schema="operational",
    )
    op.add_column(
        "provider",
        sa.Column("work_end_hour", sa.Integer, nullable=True),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_column("provider", "work_end_hour", schema="operational")
    op.drop_column("provider", "work_start_hour", schema="operational")
    op.drop_column("provider", "work_days", schema="operational")
