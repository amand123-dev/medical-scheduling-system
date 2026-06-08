"""add patient_account table and offer_token to waitlist_entry

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="operational",
    )

    op.add_column(
        "waitlist_entry",
        sa.Column("offer_token", postgresql.UUID(as_uuid=True), nullable=True, unique=True),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_column("waitlist_entry", "offer_token", schema="operational")
    op.drop_table("patient_account", schema="operational")
