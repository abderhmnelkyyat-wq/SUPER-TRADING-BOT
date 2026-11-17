"""Enforce a single owner account at the database level."""
from alembic import op
import sqlalchemy as sa

revision = '0005_single_owner_guard'
down_revision = '0004_external_intelligence'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    owners = bind.execute(sa.text("SELECT COUNT(*) FROM users WHERE role = 'owner'")).scalar_one()
    if owners > 1:
        raise RuntimeError('More than one owner already exists. Resolve owner records manually before applying this migration.')
    indexes = {i['name'] for i in sa.inspect(bind).get_indexes('users')}
    if 'uq_users_single_owner' not in indexes:
        op.create_index('uq_users_single_owner', 'users', ['role'], unique=True,
                        sqlite_where=sa.text("role = 'owner'"),
                        postgresql_where=sa.text("role = 'owner'"))

def downgrade():
    indexes = {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('users')}
    if 'uq_users_single_owner' in indexes:
        op.drop_index('uq_users_single_owner', table_name='users')
