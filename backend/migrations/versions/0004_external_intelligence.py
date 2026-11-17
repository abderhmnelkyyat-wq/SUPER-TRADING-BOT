"""Add external news feeds and bot/webhook intelligence intake."""
from alembic import op
import sqlalchemy as sa

revision = '0004_external_intelligence'
down_revision = '0003_trade_account_idempotency'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if 'integration_sources' not in tables:
        op.create_table(
            'integration_sources',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('kind', sa.String(length=20), nullable=False),
            sa.Column('url', sa.String(length=2048), nullable=True),
            sa.Column('token_hash', sa.String(length=64), nullable=True, unique=True),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_error', sa.String(length=300), nullable=True),
            sa.Column('created_by_id', sa.String(length=36), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )
    source_indexes = {i['name'] for i in sa.inspect(bind).get_indexes('integration_sources')}
    if 'ix_integration_source_kind_enabled' not in source_indexes:
        op.create_index('ix_integration_source_kind_enabled', 'integration_sources', ['kind', 'enabled'])

    tables = set(sa.inspect(bind).get_table_names())
    if 'intelligence_items' not in tables:
        op.create_table(
            'intelligence_items',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('source_id', sa.String(length=36), sa.ForeignKey('integration_sources.id', ondelete='CASCADE'), nullable=False),
            sa.Column('external_id', sa.String(length=200), nullable=False),
            sa.Column('item_type', sa.String(length=24), nullable=False, server_default='news'),
            sa.Column('title', sa.String(length=300), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False, server_default=''),
            sa.Column('url', sa.String(length=2048), nullable=True),
            sa.Column('symbols_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('trust_status', sa.String(length=32), nullable=False, server_default='unverified_external'),
            sa.UniqueConstraint('source_id', 'external_id', name='uq_intelligence_source_external'),
        )
    item_indexes = {i['name'] for i in sa.inspect(bind).get_indexes('intelligence_items')}
    if 'ix_intelligence_items_source_id' not in item_indexes:
        op.create_index('ix_intelligence_items_source_id', 'intelligence_items', ['source_id'])
    if 'ix_intelligence_published' not in item_indexes:
        op.create_index('ix_intelligence_published', 'intelligence_items', ['published_at'])


def downgrade():
    bind = op.get_bind()
    if 'intelligence_items' in sa.inspect(bind).get_table_names():
        indexes = {i['name'] for i in sa.inspect(bind).get_indexes('intelligence_items')}
        if 'ix_intelligence_published' in indexes:
            op.drop_index('ix_intelligence_published', table_name='intelligence_items')
        if 'ix_intelligence_items_source_id' in indexes:
            op.drop_index('ix_intelligence_items_source_id', table_name='intelligence_items')
        op.drop_table('intelligence_items')
    if 'integration_sources' in sa.inspect(bind).get_table_names():
        indexes = {i['name'] for i in sa.inspect(bind).get_indexes('integration_sources')}
        if 'ix_integration_source_kind_enabled' in indexes:
            op.drop_index('ix_integration_source_kind_enabled', table_name='integration_sources')
        op.drop_table('integration_sources')
