"""Optional salon haircut notes attached to appointment identity.

Revision ID: 0007_haircut_preferences
Revises: 0006_smart_recovery
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_haircut_preferences"
down_revision = "0006_smart_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_haircut_preferences",
        sa.Column("appointment_id", sa.Integer(),
                  sa.ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("style", sa.String(32), nullable=False, server_default="not_sure"),
        sa.Column("preferred_length", sa.String(16), nullable=False, server_default="unsure"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(notes) <= 800", name="ck_haircut_notes_length"),
        sa.CheckConstraint("style IN ('fade', 'taper', 'trim', 'buzz_cut', 'layers', 'styling', 'other', 'not_sure')", name="ck_haircut_style"),
        sa.CheckConstraint("preferred_length IN ('short', 'medium', 'long', 'unsure')", name="ck_haircut_length"),
    )


def downgrade():
    op.drop_table("booking_haircut_preferences")
