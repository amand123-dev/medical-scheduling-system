"""add offered_slot columns to waitlist_entry

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "waitlist_entry",
        sa.Column("offered_slot_start", sa.DateTime(timezone=True), nullable=True),
        schema="operational",
    )
    op.add_column(
        "waitlist_entry",
        sa.Column("offered_slot_end", sa.DateTime(timezone=True), nullable=True),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_column("waitlist_entry", "offered_slot_end", schema="operational")
    op.drop_column("waitlist_entry", "offered_slot_start", schema="operational")
