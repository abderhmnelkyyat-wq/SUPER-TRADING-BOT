from __future__ import annotations
import hashlib, hmac, secrets, uuid
from datetime import datetime, timedelta, timezone
import jwt
from .config import settings

def uid() -> str: return str(uuid.uuid4())
def now() -> datetime: return datetime.now(timezone.utc)
def hash_value(value: str, pepper: str | None = None) -> str:
    # Purpose-separated HMAC keys prevent the same stored digest across data classes.
    key = (settings.license_pepper + ':' + (pepper or 'default')).encode('utf-8')
    return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()
def hash_password(password: str) -> str:
    import hashlib as _hashlib, os
    salt = os.urandom(16)
    digest = _hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"
def verify_password(password: str, encoded: str | None) -> bool:
    import hashlib as _hashlib
    try:
        scheme, salt_hex, digest_hex = encoded.split('$', 2)
        if scheme != 'pbkdf2_sha256': return False
        check = _hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt_hex), 600_000).hex()
        return hmac.compare_digest(check, digest_hex)
    except Exception: return False
def generate_code(prefix: str) -> str:
    raw = secrets.token_hex(16).upper()
    return f'{prefix}-{raw[:8]}-{raw[8:16]}-{raw[16:24]}-{raw[24:]}'
def issue_token(user_id: str, role: str, session_id: str, device_hash: str) -> tuple[str, datetime]:
    expires = now() + timedelta(minutes=settings.access_token_minutes)
    payload = {'sub': user_id, 'role': role, 'sid': session_id, 'device': device_hash,
               'iss': settings.jwt_issuer, 'iat': now(), 'exp': expires}
    return jwt.encode(payload, settings.auth_secret, algorithm='HS256'), expires
def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.auth_secret, algorithms=['HS256'], issuer=settings.jwt_issuer)
