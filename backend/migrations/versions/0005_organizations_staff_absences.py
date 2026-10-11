"""Create organization/branch structure and scheduled staff unavailability.

Revision ID: 0005_org_staff_absences
Revises: 0004_geosmart_automation

Non-destructive: preserves all existing businesses, appointments and QR hashes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_org_staff_absences"
down_revision = "0004_geosmart_automation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.add_column("businesses", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_businesses_organization", "businesses", "organizations",
        ["organization_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_businesses_organization_id", "businesses", ["organization_id"])
    op.create_table("staff_absences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_staff_absence_time_order"))
    for column in ("business_id", "staff_id", "starts_at"):
        op.create_index(f"ix_staff_absences_{column}", "staff_absences", [column])


def downgrade():
    for column in ("starts_at", "staff_id", "business_id"):
        op.drop_index(f"ix_staff_absences_{column}", table_name="staff_absences")
    op.drop_table("staff_absences")
    op.drop_index("ix_businesses_organization_id", table_name="businesses")
    op.drop_constraint("fk_businesses_organization", "businesses", type_="foreignkey")
    op.drop_column("businesses", "organization_id")
    op.drop_table("organizations")
