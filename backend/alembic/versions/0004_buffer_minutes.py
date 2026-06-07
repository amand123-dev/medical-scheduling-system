"""add buffer_minutes to practice_settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-05
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "practice_settings",
        sa.Column("buffer_minutes", sa.Integer, nullable=False, server_default="0"),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_column("practice_settings", "buffer_minutes", schema="operational")
