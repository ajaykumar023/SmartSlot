"""Customer recovery consent, explicit service equivalence and audit history.

Revision ID: 0006_smart_recovery
Revises: 0005_org_staff_absences
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_smart_recovery"
down_revision = "0005_org_staff_absences"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recovery_policies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("allow_staff_substitution", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("allow_branch_transfer", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("max_delay_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("max_delay_minutes >= 0 AND max_delay_minutes <= 30", name="ck_recovery_max_delay"))
    op.create_index("ix_recovery_policies_appointment_id", "recovery_policies", ["appointment_id"])
    op.create_table("service_transfers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_service_id", sa.Integer, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_service_id", sa.Integer, sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("source_service_id", "target_service_id", name="uq_service_transfer_pair"))
    for col in ("organization_id", "source_service_id", "target_service_id"):
        op.create_index("ix_service_transfers_"+col, "service_transfers", [col])
    op.create_table("recovery_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("from_business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("to_business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("from_service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("to_service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("from_staff_id", sa.Integer, sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("to_staff_id", sa.Integer, sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("previous_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("new_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(48), nullable=False),
        sa.Column("actor", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_recovery_events_appointment_id", "recovery_events", ["appointment_id"])


def downgrade():
    op.drop_index("ix_recovery_events_appointment_id", table_name="recovery_events")
    op.drop_table("recovery_events")
    for col in ("organization_id", "source_service_id", "target_service_id"):
        op.drop_index("ix_service_transfers_"+col, table_name="service_transfers")
    op.drop_table("service_transfers")
    op.drop_index("ix_recovery_policies_appointment_id", table_name="recovery_policies")
    op.drop_table("recovery_policies")
