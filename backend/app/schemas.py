from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=12, max_length=200)
    device_id: str = Field(min_length=24, max_length=200)
    device_label: str = Field(default='Unknown device', min_length=2, max_length=120)
    referral_code: str | None = Field(default=None, max_length=32)

class SubscriptionRequestIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    payment_method: str = Field(min_length=2, max_length=80)
    payment_reference: str = Field(min_length=4, max_length=140)
    payment_proof_note: str | None = Field(default=None, max_length=1200)
    referral_code: str | None = Field(default=None, max_length=32)

class ActivateIn(BaseModel):
    email: EmailStr
    activation_code: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=12, max_length=200)
    device_id: str = Field(min_length=24, max_length=200)
    device_label: str = Field(default='Unknown device', min_length=2, max_length=120)

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    device_id: str = Field(min_length=24, max_length=200)
    device_label: str = Field(default='Unknown device', min_length=2, max_length=120)

class ReviewRequestIn(BaseModel):
    decision: str = Field(pattern='^(approve|reject)$')
    note: str | None = Field(default=None, max_length=1000)

class AdminLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    device_id: str = Field(min_length=24, max_length=200)

class MT5ClaimIn(BaseModel):
    link_code: str = Field(min_length=20, max_length=100)
    account_login: str = Field(min_length=3, max_length=40)
    server_name: str = Field(min_length=2, max_length=120)

class ClosedTradeIn(BaseModel):
    external_position_id: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=2, max_length=40)
    side: str = Field(pattern='^(BUY|SELL)$')
    volume: float = Field(gt=0, le=1_000_000)
    gross_profit: float = Field(ge=-1e12, le=1e12)
    swap: float = Field(ge=-1e12, le=1e12)
    commission: float = Field(ge=-1e12, le=1e12)
    currency: str = Field(default='USD', min_length=3, max_length=8, pattern=r'^[A-Za-z0-9]{3,8}$')
    closed_at: str = Field(min_length=10, max_length=40)

class FeePaymentIn(BaseModel):
    payment_reference: str = Field(min_length=4, max_length=140)

class AdminNoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)

class MT5LinkIn(BaseModel):
    account_login: str = Field(min_length=3, max_length=40)
    server_name: str = Field(min_length=2, max_length=120)

class TradingSettingsIn(BaseModel):
    auto_trading_enabled: bool
    accept_risk_disclosure: bool
    live_trading_enabled: bool = False
    accept_live_risk_disclosure: bool = False

class MarketSignalIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=40, pattern=r'^[A-Za-z0-9._-]+$')
    timeframe: str = Field(min_length=2, max_length=12, pattern=r'^[A-Za-z0-9]+$')
    direction: str = Field(pattern='^(BUY|SELL)$')
    confidence: float = Field(ge=0, le=1)
    entry_price: float = Field(gt=0, le=1e15)
    stop_loss: float = Field(gt=0, le=1e15)
    take_profit: float = Field(gt=0, le=1e15)
    bar_time: str = Field(min_length=10, max_length=40)
    strategy_votes: list[dict[str, str]] = Field(min_length=1, max_length=12)


class IntegrationSourceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(pattern='^(rss|webhook|telegram)$')
    url: str | None = Field(default=None, max_length=2048)

class IntegrationSourceEnabledIn(BaseModel):
    enabled: bool

class IntelligenceWebhookIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    external_id: str | None = Field(default=None, max_length=200)
    item_type: str = Field(default='news', pattern='^(news|market_event|bot_message)$')
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default='', max_length=5000)
    url: str | None = Field(default=None, max_length=2048)
    published_at: str | None = Field(default=None, max_length=40)
    symbols: list[str] = Field(default_factory=list, max_length=20)


class AssistantHistoryEntry(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=2000)

class AssistantChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[AssistantHistoryEntry] = Field(default_factory=list, max_length=8)
    consent_external_ai: bool = False
