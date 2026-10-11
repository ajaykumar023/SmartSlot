"""Original single-demo schema; kept frozen for forward migration safety."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("businesses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False))
    op.create_table("staff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False))
    op.create_table("staff_services",
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("availability",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False))
    op.create_table("appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(16), nullable=False),
        sa.Column("qr_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_id", "reference", name="uq_appointment_reference"))
    op.create_table("waitlist_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("preferred_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("slot_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for table, cols in (("services", ["business_id"]), ("staff", ["business_id"]),
        ("availability", ["business_id", "staff_id"]), ("appointments", ["business_id", "staff_id", "customer_email", "reference", "starts_at"]),
        ("waitlist_entries", ["business_id"]), ("slot_offers", ["business_id"]), ("notifications", ["business_id", "customer_email"])):
        for column in cols:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("ix_appointments_status", "appointments", ["status"])


def downgrade():
    op.drop_index("ix_appointments_status", table_name="appointments")
    for table, cols in (("services", ["business_id"]), ("staff", ["business_id"]),
        ("availability", ["business_id", "staff_id"]), ("appointments", ["business_id", "staff_id", "customer_email", "reference", "starts_at"]),
        ("waitlist_entries", ["business_id"]), ("slot_offers", ["business_id"]), ("notifications", ["business_id", "customer_email"])):
        for column in cols:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
    for table in ("notifications", "slot_offers", "waitlist_entries", "appointments", "availability", "staff_services", "staff", "services", "businesses"):
        op.drop_table(table)
