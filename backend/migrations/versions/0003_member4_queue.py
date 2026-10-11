"""Member 4 customer arrival and manual/simulated professional presence."""
from alembic import op
import sqlalchemy as sa

revision = "0003_member4_queue"
down_revision = "0002_multi_industry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("customer_arrivals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("eta_minutes", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("eta_minutes IS NULL OR (eta_minutes >= 0 AND eta_minutes <= 180)", name="ck_arrival_eta"))
    op.create_index("ix_arrivals_appointment_id", "customer_arrivals", ["appointment_id"])
    op.create_table("staff_presence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="admin_demo"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_id", "staff_id", name="uq_presence_business_staff"))
    op.create_index("ix_presence_business_id", "staff_presence", ["business_id"])


def downgrade():
    op.drop_index("ix_presence_business_id", table_name="staff_presence")
    op.drop_table("staff_presence")
    op.drop_index("ix_arrivals_appointment_id", table_name="customer_arrivals")
    op.drop_table("customer_arrivals")
