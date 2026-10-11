"""Authenticated identities, webhook delivery ledger and PG booking exclusion.

Revision ID: 0009_auth_conflicts_delivery
Revises: 0008_general_service_intake
"""
from alembic import op
import sqlalchemy as sa

revision = '0009_auth_conflicts_delivery'
down_revision = '0008_general_service_intake'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('password_salt', sa.String(64), nullable=False),
        sa.Column('password_hash', sa.String(128), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('auth_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_user_accounts_email', 'user_accounts', ['email'], unique=True)
    op.create_table('account_business_roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('user_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('business_id', sa.Integer(), sa.ForeignKey('businesses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(24), nullable=False),
        sa.Column('staff_id', sa.Integer(), sa.ForeignKey('staff.id', ondelete='SET NULL')),
        sa.UniqueConstraint('account_id', 'business_id', 'role', name='uq_account_business_role'),
        sa.CheckConstraint("role IN ('customer','admin','employee')", name='ck_account_role_allowed'))
    op.create_index('ix_account_business_roles_account_id', 'account_business_roles', ['account_id'])
    op.create_index('ix_account_business_roles_business_id', 'account_business_roles', ['business_id'])
    op.create_table('notification_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('notifications.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('status', sa.String(24), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.String(200)),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('delivered_at', sa.DateTime(timezone=True)))

    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite test runs do not support PostgreSQL exclusion constraints.

    # Existing conflicts must be resolved explicitly; never silently discard bookings.
    overlap = bind.execute(sa.text('''
       SELECT a.id, b.id FROM appointments a
       JOIN appointments b ON a.staff_id = b.staff_id AND a.id < b.id
       WHERE a.status IN ('confirmed','checked_in','at_risk')
         AND b.status IN ('confirmed','checked_in','at_risk')
         AND tstzrange(a.starts_at, a.ends_at + a.buffer_minutes * INTERVAL '1 minute', '[)')
          && tstzrange(b.starts_at, b.ends_at + b.buffer_minutes * INTERVAL '1 minute', '[)')
       LIMIT 1
    ''')).first()
    if overlap:
        raise RuntimeError(f'Existing active booking conflict: appointment IDs {overlap[0]} and {overlap[1]}; fix them before applying 0009.')
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')
    op.add_column('appointments', sa.Column('occupied_until', sa.DateTime(timezone=True), nullable=True))
    op.execute('''UPDATE appointments SET occupied_until = ends_at + buffer_minutes * INTERVAL '1 minute' ''')
    op.execute('''
    CREATE FUNCTION aetherx_set_occupied_until() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      NEW.occupied_until := NEW.ends_at + NEW.buffer_minutes * INTERVAL '1 minute';
      RETURN NEW;
    END $$
    ''')
    op.execute('''
    CREATE TRIGGER aetherx_occupied_until_trg
    BEFORE INSERT OR UPDATE OF starts_at, ends_at, buffer_minutes, occupied_until ON appointments
    FOR EACH ROW EXECUTE FUNCTION aetherx_set_occupied_until()
    ''')
    op.alter_column('appointments', 'occupied_until', nullable=False)
    op.execute('''
    ALTER TABLE appointments ADD CONSTRAINT ex_aetherx_active_staff_occupied
    EXCLUDE USING gist (
        staff_id WITH =,
        tstzrange(starts_at, occupied_until, '[)') WITH &&
    ) WHERE (status IN ('confirmed','checked_in','at_risk'))
    ''')


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ex_aetherx_active_staff_occupied')
        op.execute('DROP TRIGGER IF EXISTS aetherx_occupied_until_trg ON appointments')
        op.execute('DROP FUNCTION IF EXISTS aetherx_set_occupied_until()')
        op.drop_column('appointments', 'occupied_until')
    op.drop_table('notification_deliveries')
    op.drop_index('ix_account_business_roles_business_id', table_name='account_business_roles')
    op.drop_index('ix_account_business_roles_account_id', table_name='account_business_roles')
    op.drop_table('account_business_roles')
    op.drop_index('ix_user_accounts_email', table_name='user_accounts')
    op.drop_table('user_accounts')
