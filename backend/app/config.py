from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv('APP_NAME', 'بوت التداول الفائق | SUPER TRADING BOT')
    environment: str = os.getenv('APP_ENV', 'development')
    database_url: str = os.getenv('DATABASE_URL', 'sqlite:///./data/super_trading_bot.db')
    auth_secret: str = os.getenv('AUTH_SECRET', 'CHANGE_ME_AUTH_SECRET_FOR_LOCAL_DEVELOPMENT_ONLY')
    license_pepper: str = os.getenv('LICENSE_PEPPER', 'CHANGE_ME_LICENSE_PEPPER_FOR_LOCAL_DEVELOPMENT_ONLY')
    jwt_issuer: str = os.getenv('JWT_ISSUER', 'super-trading-bot')
    access_token_minutes: int = int(os.getenv('ACCESS_TOKEN_MINUTES', '720'))
    subscription_price_usd: int = int(os.getenv('SUBSCRIPTION_PRICE_USD', '0'))
    performance_fee_rate: float = float(os.getenv('PERFORMANCE_FEE_RATE', '0.30'))
    public_app_url: str = os.getenv('PUBLIC_APP_URL', 'http://localhost:8000')
    live_trading_enabled: bool = os.getenv('LIVE_TRADING_ENABLED', 'false').lower() == 'true'
    mt5_demo_only: bool = os.getenv('MT5_DEMO_ONLY', 'true').lower() == 'true'
    cors_origins: tuple[str, ...] = tuple(x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:8000').split(',') if x.strip())
    telegram_bot_token: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    admin_telegram_chat_id: str = os.getenv('ADMIN_TELEGRAM_CHAT_ID', '')
    smtp_host: str = os.getenv('SMTP_HOST', '')
    smtp_port: int = int(os.getenv('SMTP_PORT', '587'))
    smtp_user: str = os.getenv('SMTP_USER', '')
    smtp_password: str = os.getenv('SMTP_PASSWORD', '')
    smtp_from: str = os.getenv('SMTP_FROM', '')
    ai_chat_api_url: str = os.getenv('AI_CHAT_API_URL', '')
    ai_chat_api_key: str = os.getenv('AI_CHAT_API_KEY', '')
    ai_chat_model: str = os.getenv('AI_CHAT_MODEL', '')
    news_poll_interval_seconds: int = int(os.getenv('NEWS_POLL_INTERVAL_SECONDS', '300'))

    @property
    def ai_chat_ready(self) -> bool:
        if not (self.ai_chat_api_url and self.ai_chat_api_key and self.ai_chat_model):
            return False
        try:
            parts = urlsplit(self.ai_chat_api_url)
            return bool(parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password and parts.port in (None, 443))
        except ValueError:
            return False

    def validate(self) -> None:
        if self.news_poll_interval_seconds < 0 or self.news_poll_interval_seconds > 86400:
            raise RuntimeError('NEWS_POLL_INTERVAL_SECONDS must be between 0 and 86400.')
        if self.subscription_price_usd != 0:
            raise RuntimeError('Subscription is free in this release.')
        if abs(self.performance_fee_rate - 0.30) > 1e-9:
            raise RuntimeError('Performance fee is fixed at 30% in this release.')
        if self.live_trading_enabled and self.environment != 'production':
            raise RuntimeError('Live trading can only be unlocked in production, never in development or test mode.')
        if self.environment == 'production':
            if len(self.auth_secret) < 48 or self.auth_secret.startswith('CHANGE_ME'):
                raise RuntimeError('Set a strong AUTH_SECRET (48+ characters) in production.')
            if len(self.license_pepper) < 48 or self.license_pepper.startswith('CHANGE_ME'):
                raise RuntimeError('Set a separate strong LICENSE_PEPPER (48+ characters) in production.')
            if self.live_trading_enabled and self.mt5_demo_only:
                raise RuntimeError('LIVE_TRADING_ENABLED cannot be true while MT5_DEMO_ONLY is true.')

settings = Settings()
