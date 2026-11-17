from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .db import get_db
from .models import ApiSession, User
from .security import decode_token, hash_value, now

bearer = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail='يلزم تسجيل الدخول')
    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail='جلسة الدخول غير صالحة أو منتهية')
    session = db.get(ApiSession, payload.get('sid'))
    if (not session or session.user_id != payload.get('sub') or session.revoked_at
            or (session.expires_at.replace(tzinfo=__import__('datetime').timezone.utc) if session.expires_at.tzinfo is None else session.expires_at) <= now()
            or session.token_hash != hash_value(credentials.credentials, pepper='session-token')):
        raise HTTPException(status_code=401, detail='تم إنهاء الجلسة')
    user = db.get(User, payload.get('sub'))
    if not user or user.status not in ('active',):
        raise HTTPException(status_code=403, detail='الحساب غير نشط')
    if session.device_hash != payload.get('device'):
        raise HTTPException(status_code=401, detail='هوية الجهاز غير متطابقة')
    return user

def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != 'owner':
        raise HTTPException(status_code=403, detail='هذه الوظيفة مخصصة لمالك التطبيق')
    return user

def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != 'customer':
        raise HTTPException(status_code=403, detail='هذه الوظيفة مخصصة لحساب العميل')
    return user
