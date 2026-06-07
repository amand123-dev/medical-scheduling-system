"""add schedule_block table and work-hour settings

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedule_block",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.provider.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="operational",
    )

    op.add_column(
        "practice_settings",
        sa.Column("work_start_hour", sa.Integer, nullable=False, server_default="8"),
        schema="operational",
    )
    op.add_column(
        "practice_settings",
        sa.Column("work_end_hour", sa.Integer, nullable=False, server_default="17"),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_column("practice_settings", "work_end_hour", schema="operational")
    op.drop_column("practice_settings", "work_start_hour", schema="operational")
    op.drop_table("schedule_block", schema="operational")
