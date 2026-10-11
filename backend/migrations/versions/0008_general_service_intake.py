"""Optional appointment-scoped service intake for all SmartSlot industries.

Revision ID: 0008_general_service_intake
Revises: 0007_haircut_preferences
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_general_service_intake"
down_revision = "0007_haircut_preferences"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_service_intakes",
        sa.Column("appointment_id", sa.Integer(),
                  sa.ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(160), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(summary) <= 160", name="ck_service_intake_summary_length"),
        sa.CheckConstraint("length(notes) <= 1200", name="ck_service_intake_notes_length"),
    )


def downgrade():
    op.drop_table("booking_service_intakes")
