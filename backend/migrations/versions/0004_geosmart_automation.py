"""Location destinations and staff-facing persistent alerts.

Revision ID: 0004_geosmart_automation
Revises: 0003_member4_queue
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_geosmart_automation"
down_revision = "0003_member4_queue"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("businesses", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("businesses", sa.Column("longitude", sa.Float(), nullable=True))
    op.create_table("admin_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(16), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_admin_alerts_business_id", "admin_alerts", ["business_id"])

def downgrade():
    op.drop_index("ix_admin_alerts_business_id", table_name="admin_alerts")
    op.drop_table("admin_alerts")
    op.drop_column("businesses", "longitude")
    op.drop_column("businesses", "latitude")
