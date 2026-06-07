"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")
    op.execute("CREATE SCHEMA IF NOT EXISTS operational")

    op.create_table(
        "patient_identity",
        sa.Column("patient_uuid", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("dob", sa.String(20), nullable=False),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="identity",
    )

    op.create_table(
        "identity_access_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accessed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="identity",
    )

    op.create_table(
        "provider",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("specialty", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        schema="operational",
    )

    op.create_table(
        "visit_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("is_new_patient", sa.Boolean, nullable=False, server_default="false"),
        schema="operational",
    )

    staff_role_enum = postgresql.ENUM(
        "admin", "provider", "front_desk", name="staffrole", schema="operational", create_type=False
    )
    op.execute("CREATE TYPE operational.staffrole AS ENUM ('admin', 'provider', 'front_desk')")

    op.create_table(
        "staff_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(200), nullable=False),
        sa.Column("role", staff_role_enum, nullable=False),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.provider.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="operational",
    )

    appt_status_enum = postgresql.ENUM(
        "scheduled",
        "completed",
        "cancelled",
        "no_show",
        name="appointmentstatus",
        schema="operational",
        create_type=False,
    )
    op.execute(
        "CREATE TYPE operational.appointmentstatus AS ENUM ('scheduled', 'completed', 'cancelled', 'no_show')"
    )

    op.create_table(
        "appointment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.provider.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "visit_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.visit_type.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", appt_status_enum, nullable=False, server_default="scheduled"),
        sa.Column("no_show_risk", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="operational",
    )

    waitlist_status_enum = postgresql.ENUM(
        "waiting",
        "offered",
        "booked",
        "declined",
        "expired",
        name="waitliststatus",
        schema="operational",
        create_type=False,
    )
    op.execute(
        "CREATE TYPE operational.waitliststatus AS ENUM ('waiting', 'offered', 'booked', 'declined', 'expired')"
    )

    op.create_table(
        "waitlist_entry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.provider.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "visit_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.visit_type.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("earliest_window", sa.Time, nullable=True),
        sa.Column("latest_window", sa.Time, nullable=True),
        sa.Column("status", waitlist_status_enum, nullable=False, server_default="waiting"),
        sa.Column("decline_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=True),
        schema="operational",
    )

    reminder_channel_enum = postgresql.ENUM(
        "sms", "email", "call", name="reminderchannel", schema="operational", create_type=False
    )
    op.execute("CREATE TYPE operational.reminderchannel AS ENUM ('sms', 'email', 'call')")

    reminder_type_enum = postgresql.ENUM(
        "standard",
        "followup",
        "call_requested",
        name="remindertype",
        schema="operational",
        create_type=False,
    )
    op.execute(
        "CREATE TYPE operational.remindertype AS ENUM ('standard', 'followup', 'call_requested')"
    )

    op.create_table(
        "reminder_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "appointment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operational.appointment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("channel", reminder_channel_enum, nullable=False),
        sa.Column("message_type", reminder_type_enum, nullable=False),
        schema="operational",
    )

    op.create_table(
        "practice_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("matcher_w1", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("matcher_w2", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("matcher_w3", sa.Float, nullable=False, server_default="0.3"),
        sa.Column("hold_window_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("risk_low_threshold", sa.Float, nullable=False, server_default="0.2"),
        sa.Column("risk_high_threshold", sa.Float, nullable=False, server_default="0.5"),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_table("practice_settings", schema="operational")
    op.drop_table("reminder_log", schema="operational")
    op.drop_table("waitlist_entry", schema="operational")
    op.drop_table("appointment", schema="operational")
    op.drop_table("staff_user", schema="operational")
    op.drop_table("visit_type", schema="operational")
    op.drop_table("provider", schema="operational")
    op.drop_table("identity_access_log", schema="identity")
    op.drop_table("patient_identity", schema="identity")

    op.execute("DROP TYPE IF EXISTS operational.remindertype")
    op.execute("DROP TYPE IF EXISTS operational.reminderchannel")
    op.execute("DROP TYPE IF EXISTS operational.waitliststatus")
    op.execute("DROP TYPE IF EXISTS operational.appointmentstatus")
    op.execute("DROP TYPE IF EXISTS operational.staffrole")

    op.execute("DROP SCHEMA IF EXISTS operational CASCADE")
    op.execute("DROP SCHEMA IF EXISTS identity CASCADE")
