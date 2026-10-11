"""Add business profiles, policies, hours, and duration snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0002_multi_industry"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("businesses", sa.Column("demo_key", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_business_demo_key", "businesses", ["demo_key"])
    op.add_column("businesses", sa.Column("category", sa.String(32), nullable=True))
    op.add_column("businesses", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("businesses", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("businesses", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("businesses", sa.Column("default_buffer_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("businesses", sa.Column("check_in_minutes", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("businesses", sa.Column("early_arrival_minutes", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("businesses", sa.Column("queue_grace_minutes", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("businesses", sa.Column("queue_shift_minutes", sa.Integer(), nullable=False, server_default="15"))
    op.add_column("businesses", sa.Column("cancellation_cutoff_hours", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("businesses", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE businesses SET category='salon', description='Fictional salon demo business', is_demo=TRUE, demo_key='salon', updated_at=CURRENT_TIMESTAMP WHERE id=1")
    op.execute("UPDATE businesses SET category='consultant', updated_at=CURRENT_TIMESTAMP WHERE category IS NULL")
    op.alter_column("businesses", "category", nullable=False)
    op.create_check_constraint("ck_business_category", "businesses", "category IN ('salon','clinic','repair_center','consultant')")
    op.create_check_constraint("ck_business_buffer_nonnegative", "businesses", "default_buffer_minutes >= 0")
    op.create_index("ix_businesses_category", "businesses", ["category"])
    op.create_index("ix_businesses_active", "businesses", ["active"])
    op.create_index("ix_businesses_is_demo", "businesses", ["is_demo"])

    op.create_table("business_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.UniqueConstraint("business_id", "weekday", name="uq_business_hours_day"),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_business_hours_weekday"))
    op.create_index("ix_business_hours_business_id", "business_hours", ["business_id"])

    op.add_column("services", sa.Column("buffer_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_service_duration", "services", "duration_minutes > 0 AND duration_minutes <= 480")
    op.create_check_constraint("ck_service_buffer", "services", "buffer_minutes >= 0")

    op.add_column("staff", sa.Column("title", sa.String(100), nullable=True))
    op.execute("UPDATE staff SET title=role")
    op.alter_column("staff", "title", nullable=False, server_default="Team member")
    op.drop_column("staff", "role")
    op.create_index("ix_staff_active", "staff", ["active"])

    op.create_unique_constraint("uq_staff_availability_day", "availability", ["business_id", "staff_id", "weekday"])
    op.create_check_constraint("ck_staff_availability_weekday", "availability", "weekday >= 0 AND weekday <= 6")

    op.add_column("appointments", sa.Column("duration_minutes", sa.Integer(), nullable=True))
    op.add_column("appointments", sa.Column("buffer_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("appointments", sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE appointments SET duration_minutes=GREATEST(1, CAST(EXTRACT(EPOCH FROM (ends_at - starts_at))/60 AS INTEGER))")
    op.alter_column("appointments", "duration_minutes", nullable=False, server_default="30")
    op.create_check_constraint("ck_appointment_time_order", "appointments", "ends_at > starts_at")
    op.create_check_constraint("ck_appointment_duration", "appointments", "duration_minutes > 0")

    op.add_column("slot_offers", sa.Column("original_starts_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("slot_offers", sa.Column("original_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("slot_offers", sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("slot_offers", sa.Column("waitlist_entry_id", sa.Integer(), sa.ForeignKey("waitlist_entries.id"), nullable=True))


def downgrade():
    op.drop_column("slot_offers", "waitlist_entry_id")
    op.drop_column("slot_offers", "responded_at")
    op.drop_column("slot_offers", "original_ends_at")
    op.drop_column("slot_offers", "original_starts_at")
    op.drop_constraint("ck_appointment_duration", "appointments", type_="check")
    op.drop_constraint("ck_appointment_time_order", "appointments", type_="check")
    op.drop_column("appointments", "checked_in_at")
    op.drop_column("appointments", "buffer_minutes")
    op.drop_column("appointments", "duration_minutes")
    op.drop_constraint("ck_staff_availability_weekday", "availability", type_="check")
    op.drop_constraint("uq_staff_availability_day", "availability", type_="unique")
    op.drop_index("ix_staff_active", table_name="staff")
    op.add_column("staff", sa.Column("role", sa.String(100), nullable=True))
    op.execute("UPDATE staff SET role=title")
    op.alter_column("staff", "role", nullable=False, server_default="Specialist")
    op.drop_column("staff", "title")
    op.drop_constraint("ck_service_buffer", "services", type_="check")
    op.drop_constraint("ck_service_duration", "services", type_="check")
    op.drop_column("services", "buffer_minutes")
    op.drop_index("ix_business_hours_business_id", table_name="business_hours")
    op.drop_table("business_hours")
    for name in ("ix_businesses_is_demo", "ix_businesses_active", "ix_businesses_category"):
        op.drop_index(name, table_name="businesses")
    op.drop_constraint("ck_business_buffer_nonnegative", "businesses", type_="check")
    op.drop_constraint("ck_business_category", "businesses", type_="check")
    for name in ("updated_at", "cancellation_cutoff_hours", "queue_shift_minutes", "queue_grace_minutes", "early_arrival_minutes", "check_in_minutes", "default_buffer_minutes", "is_demo", "active", "description", "category"):
        op.drop_column("businesses", name)
    op.drop_constraint("uq_business_demo_key", "businesses", type_="unique")
    op.drop_column("businesses", "demo_key")
