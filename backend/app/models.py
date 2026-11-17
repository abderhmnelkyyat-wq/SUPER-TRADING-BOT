from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Integer, Float, Numeric, Text, UniqueConstraint, Index, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def utcnow(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    __table_args__ = (Index('uq_users_single_owner', 'role', unique=True,
                            sqlite_where=sql_text("role = 'owner'"),
                            postgresql_where=sql_text("role = 'owner'")),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auto_trading_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trading_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    live_trading_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role: Mapped[str] = mapped_column(String(16), default='customer', nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='pending_payment', index=True, nullable=False)
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    referred_by_user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    subscription_requests = relationship('SubscriptionRequest', back_populates='user', foreign_keys='SubscriptionRequest.user_id')
    license = relationship('License', back_populates='user', uselist=False)

class SubscriptionRequest(Base):
    __tablename__ = 'subscription_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    amount_usd: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(80), nullable=False)
    payment_reference: Mapped[str] = mapped_column(String(140), nullable=False)
    payment_proof_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True, nullable=False)
    admin_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    user = relationship('User', back_populates='subscription_requests', foreign_keys=[user_id])

class License(Base):
    __tablename__ = 'licenses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='issued', index=True, nullable=False)
    device_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    device_label: Mapped[str | None] = mapped_column(String(120))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    user = relationship('User', back_populates='license')

class ApiSession(Base):
    __tablename__ = 'api_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class SecurityEvent(Base):
    __tablename__ = 'security_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    license_id: Mapped[str | None] = mapped_column(ForeignKey('licenses.id'))
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    device_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class MT5LinkIntent(Base):
    __tablename__ = 'mt5_link_intents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_account_login: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_server_name: Mapped[str] = mapped_column(String(120), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class MT5Bridge(Base):
    __tablename__ = 'mt5_bridges'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    link_intent_id: Mapped[str] = mapped_column(ForeignKey('mt5_link_intents.id'), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    account_login: Mapped[str] = mapped_column(String(40), nullable=False)
    server_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='active', index=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class ClosedTrade(Base):
    __tablename__ = 'closed_trades'
    __table_args__ = (UniqueConstraint('bridge_id', 'external_position_id', name='uq_trade_bridge_position'), Index('ix_trade_user_closed', 'user_id', 'closed_at'), Index('uq_trade_user_account_position', 'user_id', 'account_login', 'server_name', 'external_position_id', unique=True))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    bridge_id: Mapped[str] = mapped_column(ForeignKey('mt5_bridges.id'), nullable=False)
    account_login: Mapped[str | None] = mapped_column(String(40))
    server_name: Mapped[str | None] = mapped_column(String(120))
    external_position_id: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    gross_profit: Mapped[float] = mapped_column(Float, nullable=False)
    swap: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    commission: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    net_profit: Mapped[float] = mapped_column(Float, nullable=False)
    fee_rate: Mapped[float] = mapped_column(Float, nullable=False)
    fee_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default='USD', nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class PerformanceFee(Base):
    __tablename__ = 'performance_fees'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    trade_id: Mapped[str] = mapped_column(ForeignKey('closed_trades.id'), unique=True, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default='USD', nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='due', index=True, nullable=False)
    paid_reference: Mapped[str | None] = mapped_column(String(140))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(36))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketSignal(Base):
    __tablename__ = 'market_signals'
    __table_args__ = (UniqueConstraint('bridge_id', 'symbol', 'timeframe', 'bar_time', name='uq_signal_bar'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    bridge_id: Mapped[str] = mapped_column(ForeignKey('mt5_bridges.id'), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(12), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    strategy_votes: Mapped[str] = mapped_column(Text, nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RateLimitBucket(Base):
    __tablename__ = 'rate_limit_buckets'
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class IntegrationSource(Base):
    __tablename__ = 'integration_sources'
    __table_args__ = (Index('ix_integration_source_kind_enabled', 'kind', 'enabled'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # rss, webhook, telegram
    url: Mapped[str | None] = mapped_column(String(2048))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    items = relationship('IntelligenceItem', back_populates='source', cascade='all, delete-orphan')


class IntelligenceItem(Base):
    __tablename__ = 'intelligence_items'
    __table_args__ = (
        UniqueConstraint('source_id', 'external_id', name='uq_intelligence_source_external'),
        Index('ix_intelligence_published', 'published_at'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('integration_sources.id', ondelete='CASCADE'), index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    item_type: Mapped[str] = mapped_column(String(24), default='news', nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default='', nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    symbols_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    trust_status: Mapped[str] = mapped_column(String(32), default='unverified_external', nullable=False)
    source = relationship('IntegrationSource', back_populates='items')
