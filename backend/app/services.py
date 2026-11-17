from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .config import settings
from .models import AuditLog, User, License, ApiSession, SecurityEvent, PerformanceFee, ClosedTrade
from .security import uid, now, hash_value, generate_code, hash_password, issue_token


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def audit(db: Session, actor_type: str, actor_id: str | None, action: str, target_type: str | None = None, target_id: str | None = None, metadata: dict | None = None):
    db.add(AuditLog(id=uid(), actor_type=actor_type, actor_id=actor_id, action=action, target_type=target_type,
                    target_id=target_id, metadata_json=json.dumps(metadata or {}, ensure_ascii=False)))

def add_security_event(db: Session, user_id: str | None, license_id: str | None, event_type: str, device_hash: str | None, details: str):
    db.add(SecurityEvent(id=uid(), user_id=user_id, license_id=license_id, event_type=event_type, device_hash=device_hash, details=details))

def create_session(db: Session, user: User, raw_device_id: str) -> tuple[str, datetime]:
    device_hash = hash_value(raw_device_id, pepper='device-identity')
    session_id = uid()
    token, expires = issue_token(user.id, user.role, session_id, device_hash)
    db.add(ApiSession(id=session_id, user_id=user.id, token_hash=hash_value(token, pepper='session-token'), device_hash=device_hash, expires_at=expires))
    return token, expires

def user_view(user: User):
    lic = user.license
    return {'id': user.id, 'full_name': user.full_name, 'email': user.email, 'status': user.status,
            'role': user.role, 'referral_code': user.referral_code,
            'referral_url': f'{settings.public_app_url.rstrip("/")}/?ref={user.referral_code}' if user.referral_code else None,
            'license_status': lic.status if lic else None, 'license_device': lic.device_label if lic else None}

def calculate_fee(gross_profit: float, swap: float, commission: float, rate: float = 0.30) -> tuple[float, float]:
    net = float(Decimal(str(gross_profit + swap + commission)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    fee = float((Decimal(str(max(net, 0))) * Decimal(str(rate))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    return net, fee
