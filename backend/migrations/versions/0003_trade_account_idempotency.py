"""Scope MT5 close accounting by customer broker account, not bridge token."""
from alembic import op
import sqlalchemy as sa

revision = '0003_trade_account_idempotency'
down_revision = '0002_rate_limits'
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c['name'] for c in inspector.get_columns('closed_trades')}
    if 'account_login' not in columns:
        op.add_column('closed_trades', sa.Column('account_login', sa.String(length=40), nullable=True))
    if 'server_name' not in columns:
        op.add_column('closed_trades', sa.Column('server_name', sa.String(length=120), nullable=True))
    # Backfill old records from the bridge that originally submitted them.
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        op.execute("UPDATE closed_trades SET account_login=(SELECT account_login FROM mt5_bridges WHERE mt5_bridges.id=closed_trades.bridge_id) WHERE account_login IS NULL")
        op.execute("UPDATE closed_trades SET server_name=(SELECT server_name FROM mt5_bridges WHERE mt5_bridges.id=closed_trades.bridge_id) WHERE server_name IS NULL")
    else:
        op.execute("UPDATE closed_trades SET account_login=mt5_bridges.account_login, server_name=mt5_bridges.server_name FROM mt5_bridges WHERE mt5_bridges.id=closed_trades.bridge_id AND (closed_trades.account_login IS NULL OR closed_trades.server_name IS NULL)")
    indexes = {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('closed_trades')}
    if 'uq_trade_user_account_position' not in indexes:
        op.create_index('uq_trade_user_account_position', 'closed_trades',
                        ['user_id','account_login','server_name','external_position_id'], unique=True)

def downgrade():
    indexes = {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('closed_trades')}
    if 'uq_trade_user_account_position' in indexes:
        op.drop_index('uq_trade_user_account_position', table_name='closed_trades')
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('closed_trades')}
    if 'server_name' in columns:
        op.drop_column('closed_trades','server_name')
    if 'account_login' in columns:
        op.drop_column('closed_trades','account_login')
