"""Add explicit, separate customer consent for real-money trading."""
from alembic import op
import sqlalchemy as sa

revision = '0006_live_trading_consent'
down_revision = '0005_single_owner_guard'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('users')}
    # The legacy 0001 migration creates the current ORM metadata on a fresh DB.
    # Guard here so fresh installs and upgrades from older DBs both work.
    if 'live_trading_consent_at' not in columns:
        op.add_column('users', sa.Column('live_trading_consent_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('users')}
    if 'live_trading_consent_at' in columns:
        op.drop_column('users', 'live_trading_consent_at')
