"""Persistent throttling buckets for public and authentication endpoints."""
from alembic import op
from app import models  # noqa: F401

revision = '0002_rate_limits'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    models.RateLimitBucket.__table__.create(bind=op.get_bind(), checkfirst=True)

def downgrade():
    models.RateLimitBucket.__table__.drop(bind=op.get_bind(), checkfirst=True)
