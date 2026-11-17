from __future__ import annotations
import json
import secrets
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from contextlib import asynccontextmanager
import jwt
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session, aliased
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import get_db, init_db, SessionLocal
from .deps import get_current_user, require_owner, require_customer
from .models import (User, SubscriptionRequest, License, ApiSession, SecurityEvent, MT5LinkIntent,
                     MT5Bridge, ClosedTrade, PerformanceFee, AuditLog, MarketSignal, RateLimitBucket,
                     IntegrationSource, IntelligenceItem)
from .schemas import (RegisterIn, SubscriptionRequestIn, ActivateIn, LoginIn, ReviewRequestIn, MT5ClaimIn,
                     ClosedTradeIn, FeePaymentIn, AdminNoteIn, AdminLoginIn, MT5LinkIn, TradingSettingsIn, MarketSignalIn,
                     IntegrationSourceIn, IntegrationSourceEnabledIn, IntelligenceWebhookIn, AssistantChatIn)
from .security import uid, now, hash_value, hash_password, verify_password, generate_code, decode_token
from .services import audit, add_security_event, create_session, user_view, calculate_fee, as_utc
from .notifications import notify_admin
from .integrations.intelligence import add_intelligence_item, item_view, parse_datetime
from .integrations.news import validate_feed_url_syntax, poll_rss_source, poll_enabled_rss_sources, inspect_rss_source
from .integrations.assistant import ask_model

settings.validate()
logger = logging.getLogger('super_trading_bot.news')

def revoke_user_bridges(db: Session, user_id: str) -> None:
    for bridge in db.scalars(select(MT5Bridge).where(MT5Bridge.user_id==user_id, MT5Bridge.status=='active')).all():
        bridge.status='revoked'
    for intent in db.scalars(select(MT5LinkIntent).where(MT5LinkIntent.user_id==user_id, MT5LinkIntent.claimed_at.is_(None), MT5LinkIntent.revoked_at.is_(None))).all():
        intent.revoked_at=now()

def enforce_rate_limit(db: Session, request: Request, action: str, identifier: str = '',
                       limit: int = 10, window_seconds: int = 900, block_seconds: int = 900) -> None:
    # Persist a bucket for both client IP and account identifier, so rotating emails
    # or restarting the API process does not immediately reset authentication limits.
    remote = request.client.host if request.client else 'unknown'
    keys = [f'{action}:ip:{remote}']
    if identifier:
        keys.append(f'{action}:id:{identifier.strip().lower()}')
    current = now()
    blocked = False
    for raw_key in keys:
        key = hash_value(raw_key, pepper='rate-limit')
        row = db.get(RateLimitBucket, key)
        if row is None:
            row = RateLimitBucket(key_hash=key, hits=0, window_started_at=current, updated_at=current)
            db.add(row)
        start = as_utc(row.window_started_at)
        if row.blocked_until and as_utc(row.blocked_until) > current:
            blocked = True
            continue
        if (current - start).total_seconds() >= window_seconds:
            row.hits = 0
            row.window_started_at = current
            row.blocked_until = None
        row.hits += 1
        row.updated_at = current
        if row.hits > limit:
            row.blocked_until = current + timedelta(seconds=block_seconds)
            blocked = True
    db.commit()
    if blocked:
        raise HTTPException(429, 'محاولات كثيرة خلال وقت قصير. انتظر قليلًا ثم حاول مرة أخرى.')


def _poll_news_once() -> list[dict]:
    db = SessionLocal()
    try:
        return poll_enabled_rss_sources(db)
    finally:
        db.close()


async def _news_poll_loop() -> None:
    # A single API worker is recommended for the built-in scheduler.
    while True:
        try:
            results = await asyncio.to_thread(_poll_news_once)
            failed = sum(1 for row in results if not row.get('ok'))
            logger.info('Scheduled RSS poll: %s sources, %s failed', len(results), failed)
        except Exception:
            logger.exception('Scheduled RSS poll failed')
        await asyncio.sleep(settings.news_poll_interval_seconds)


@asynccontextmanager
async def lifespan(application: FastAPI):
    if settings.environment != 'production':
        init_db()
    poll_task = None
    if settings.news_poll_interval_seconds > 0:
        poll_task = asyncio.create_task(_news_poll_loop())
        application.state.news_polling_enabled = True
    else:
        application.state.news_polling_enabled = False
    try:
        yield
    finally:
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

app = FastAPI(title=settings.app_name, version='2.0.0', docs_url='/api/docs' if settings.environment != 'production' else None,
              redoc_url=None, openapi_url='/api/openapi.json' if settings.environment != 'production' else None, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                   allow_methods=['GET','POST','PATCH','DELETE'], allow_headers=['Authorization','Content-Type','X-Bridge-Token','X-Integration-Token','X-Telegram-Bot-Api-Secret-Token'])
BASE = Path(__file__).resolve().parents[2]
FRONTEND = BASE / 'frontend'
OWNER_CONSOLE = Path(__file__).resolve().parents[1] / 'owner_console'

@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.scheme == 'https': response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

@app.get('/api/health')
def health():
    return {'status':'ok', 'service':'SUPER TRADING BOT', 'version':'2.0.0', 'trading_mode':'live_gated' if settings.live_trading_enabled and not settings.mt5_demo_only else 'demo_only', 'live_trading_enabled':bool(settings.live_trading_enabled and not settings.mt5_demo_only)}

@app.get('/api/public/config')
def public_config():
    return {'app_name':settings.app_name, 'subscription_price_usd':0, 'subscription_type':'free',
            'performance_fee_rate':0.30, 'referral_reward':0, 'trading_mode':'live_gated' if settings.live_trading_enabled and not settings.mt5_demo_only else 'demo_only', 'live_trading_enabled':bool(settings.live_trading_enabled and not settings.mt5_demo_only)}

@app.post('/api/auth/register', status_code=201)
def register_customer(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    enforce_rate_limit(db, request, 'customer_register', email, limit=5, window_seconds=900, block_seconds=1800)
    if db.scalar(select(User).where(func.lower(User.email)==email)):
        raise HTTPException(409, 'هذا البريد مسجل بالفعل. سجّل الدخول بدلًا من إنشاء حساب جديد.')
    referrer = None
    if payload.referral_code:
        referrer = db.scalar(select(User).where(User.referral_code==payload.referral_code, User.role=='customer', User.status=='active'))
        if not referrer:
            raise HTTPException(400, 'رابط الإحالة غير صالح')
    user = User(id=uid(), full_name=payload.full_name, email=email, phone=payload.phone,
                password_hash=hash_password(payload.password), role='customer', status='active',
                referral_code=generate_code('REF').replace('-', ''),
                referred_by_user_id=referrer.id if referrer else None)
    device_hash = hash_value(payload.device_id, pepper='device-identity')
    # Internal license record preserves device/account controls; no paid activation code is issued.
    license_secret = generate_code('FREE')
    lic = License(id=uid(), user_id=user.id, code_hash=hash_value(license_secret, pepper='license-code'),
                  status='active', device_hash=device_hash, device_label=payload.device_label[:120],
                  activated_at=now(), last_seen_at=now())
    db.add(user); db.add(lic); db.flush()
    token, expires = create_session(db, user, payload.device_id)
    audit(db, 'customer', user.id, 'customer.registered_free', 'user', user.id,
          {'plan':'free','performance_fee_rate':0.30,'device_label':lic.device_label})
    db.commit()
    return {'access_token':token,'token_type':'bearer','expires_at':expires.isoformat(),
            'user':user_view(user),'plan':'free','performance_fee_rate':0.30,
            'message':'تم إنشاء حسابك المجاني بنجاح. لا توجد رسوم اشتراك أو تفعيل.'}

@app.post('/api/public/subscriptions', status_code=201)
async def create_subscription_request(payload: SubscriptionRequestIn, request: Request, db: Session = Depends(get_db)):
    raise HTTPException(410, 'تم إلغاء نظام الاشتراكات المدفوعة. أنشئ حسابًا مجانيًا من صفحة التسجيل الجديدة.')

@app.post('/api/auth/activate')
def activate(payload: ActivateIn, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower(); enforce_rate_limit(db, request, 'activate', email, limit=8, window_seconds=900, block_seconds=1800); user = db.scalar(select(User).where(func.lower(User.email)==email))
    if not user: raise HTTPException(404, 'لا يوجد طلب لهذا البريد')
    if user.role != 'customer': raise HTTPException(403, 'مسار التفعيل مخصص لحسابات العملاء فقط')
    lic = db.scalar(select(License).where(License.user_id==user.id))
    if not lic or lic.code_hash != hash_value(payload.activation_code, pepper='license-code'):
        add_security_event(db, user.id, lic.id if lic else None, 'invalid_activation_code', hash_value(payload.device_id, pepper='device-identity'), 'Invalid or unknown activation code')
        db.commit(); raise HTTPException(400, 'رمز التفعيل غير صحيح')
    if user.status not in ('paid_pending_activation','active'):
        raise HTTPException(403, 'الاشتراك غير معتمد أو الحساب موقوف')
    device_hash = hash_value(payload.device_id, pepper='device-identity')
    if lic.status == 'suspended':
        raise HTTPException(423, 'الترخيص معلق حتى يراجعه مالك التطبيق ويفك التعليق يدويًا.')
    if lic.device_hash and lic.device_hash != device_hash:
        lic.status='suspended'; lic.suspended_until=None; user.auto_trading_enabled=False; user.trading_consent_at=None; user.live_trading_consent_at=None
        revoke_user_bridges(db, user.id)
        for s in db.scalars(select(ApiSession).where(ApiSession.user_id==user.id, ApiSession.revoked_at.is_(None))).all(): s.revoked_at=now()
        add_security_event(db, user.id, lic.id, 'duplicate_device_activation', device_hash, 'Activation code presented from a different device; license temporarily suspended')
        audit(db, 'system', None, 'license.auto_suspended', 'license', lic.id, {'reason':'device_mismatch'})
        db.commit(); raise HTTPException(423, 'تم تعليق الترخيص مؤقتًا بسبب محاولة استخدامه من جهاز آخر. يستطيع مالك التطبيق إعادة التفعيل.')
    if lic.status == 'active':
        raise HTTPException(409, 'التطبيق مفعل بالفعل على هذا الجهاز. استخدم تسجيل الدخول.')
    user.password_hash = hash_password(payload.password)
    user.status='active'; lic.status='active'; lic.device_hash=device_hash; lic.device_label=payload.device_label[:120]
    lic.activated_at=now(); lic.last_seen_at=now()
    if not user.referral_code: user.referral_code=generate_code('REF').replace('-','')
    token, expires = create_session(db, user, payload.device_id)
    audit(db, 'customer', user.id, 'license.activated', 'license', lic.id, {'device_label':lic.device_label})
    db.commit()
    return {'access_token':token,'token_type':'bearer','expires_at':expires.isoformat(),'user':user_view(user)}

@app.post('/api/auth/login')
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(db, request, 'customer_login', str(payload.email), limit=8, window_seconds=900, block_seconds=1800)
    user = db.scalar(select(User).where(func.lower(User.email)==str(payload.email).lower()))
    if not user or user.role != 'customer' or not verify_password(payload.password, user.password_hash): raise HTTPException(401, 'البريد أو كلمة المرور غير صحيحة')
    if user.status != 'active': raise HTTPException(403, 'الحساب غير نشط')
    if user.role == 'customer':
        lic = db.scalar(select(License).where(License.user_id==user.id))
        device_hash = hash_value(payload.device_id, pepper='device-identity')
        if not lic: raise HTTPException(403, 'ترخيص التطبيق غير موجود')
        if lic.status == 'suspended': raise HTTPException(423, 'الترخيص معلق حتى يراجعه مالك التطبيق ويفك التعليق يدويًا')
        if lic.status != 'active': raise HTTPException(403, 'ترخيص التطبيق غير نشط')
        if lic.device_hash != device_hash:
            lic.status='suspended'; lic.suspended_until=None; user.auto_trading_enabled=False; user.trading_consent_at=None; user.live_trading_consent_at=None
            revoke_user_bridges(db, user.id)
            for s in db.scalars(select(ApiSession).where(ApiSession.user_id==user.id, ApiSession.revoked_at.is_(None))).all(): s.revoked_at=now()
            add_security_event(db,user.id,lic.id,'login_device_mismatch',device_hash,'Login attempt from a different installation')
            db.commit(); raise HTTPException(423, 'تم تعليق الترخيص مؤقتًا بسبب محاولة دخول من جهاز غير معتمد')
        lic.last_seen_at=now()
    token, expires = create_session(db,user,payload.device_id)
    db.commit()
    return {'access_token':token,'token_type':'bearer','expires_at':expires.isoformat(),'user':user_view(user)}

@app.post('/api/auth/logout')
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db), authorization: str = Header(default='')):
    token = authorization.removeprefix('Bearer ').strip()
    if token:
        try:
            payload=decode_token(token); s=db.get(ApiSession,payload.get('sid'))
            if s: s.revoked_at=now(); db.commit()
        except Exception: pass
    return {'ok':True}

@app.get('/api/account')
def account(user: User = Depends(get_current_user)):
    return user_view(user)

@app.get('/api/referral')
def referral(user: User = Depends(require_customer)):
    if not user.referral_code: raise HTTPException(409, 'سيظهر رابط الإحالة بعد اعتماد الاشتراك وتفعيل الحساب')
    return {'referral_code':user.referral_code,'referral_url':f'{settings.public_app_url.rstrip("/")}/?ref={user.referral_code}',
            'reward_usd':0,'reward_policy':'لا توجد عمولة أو مكافأة إحالة'}

@app.post('/api/mt5/link')
def create_mt5_link(payload: MT5LinkIn, request: Request, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    enforce_rate_limit(db, request, 'mt5_link', user.id, limit=8, window_seconds=900, block_seconds=900)
    login = payload.account_login.strip(); server = payload.server_name.strip()
    if not login or len(login)>40 or not server or len(server)>120: raise HTTPException(422,'أدخل رقم حساب MT5 واسم الخادم بشكل صحيح')
    lic=db.scalar(select(License).where(License.user_id==user.id))
    if not lic or lic.status!='active': raise HTTPException(403,'ترخيص التطبيق غير نشط؛ لا يمكن ربط MT5')
    raw=generate_code('MT5'); intent=MT5LinkIntent(id=uid(),user_id=user.id,code_hash=hash_value(raw,pepper='mt5-link'),
        expected_account_login=login,expected_server_name=server,expires_at=now()+timedelta(minutes=15))
    db.add(intent); audit(db,'customer',user.id,'mt5.link_requested','mt5_link_intent',intent.id); db.commit()
    return {'link_code':raw,'expires_at':intent.expires_at.isoformat(),'instructions':'أدخل هذا الرمز في Windows MT5 Agent. لا ترسل كلمة مرور حساب التداول إلى التطبيق.'}

@app.post('/api/mt5/claim')
def claim_mt5(payload: MT5ClaimIn, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(db, request, 'mt5_claim', '', limit=12, window_seconds=900, block_seconds=900)
    intent=db.scalar(select(MT5LinkIntent).where(MT5LinkIntent.code_hash==hash_value(payload.link_code,pepper='mt5-link')))
    if not intent or intent.claimed_at or intent.revoked_at or as_utc(intent.expires_at)<now(): raise HTTPException(400,'رمز ربط MT5 غير صالح أو منتهي')
    linked_user=db.get(User,intent.user_id)
    linked_license=db.scalar(select(License).where(License.user_id==intent.user_id))
    if not linked_user or linked_user.status!='active' or not linked_license or linked_license.status!='active':
        raise HTTPException(403,'لا يمكن ربط MT5 قبل تفعيل اشتراك وترخيص العميل')
    if intent.expected_account_login != payload.account_login or intent.expected_server_name != payload.server_name:
        raise HTTPException(403,'بيانات حساب MT5 لا تطابق البيانات التي أدخلها العميل')
    # One active customer owner for a broker account prevents cross-customer account sharing.
    occupied = db.scalar(select(MT5Bridge).where(MT5Bridge.account_login==payload.account_login,
        MT5Bridge.server_name==payload.server_name, MT5Bridge.status=='active', MT5Bridge.user_id!=intent.user_id))
    if occupied:
        raise HTTPException(409,'حساب MT5 مرتبط بترخيص عميل آخر بالفعل؛ راجع مالك التطبيق قبل إعادة الربط')
    # One live bridge per user + broker account prevents duplicate position-fee ingestion.
    for old in db.scalars(select(MT5Bridge).where(MT5Bridge.user_id==intent.user_id,
            MT5Bridge.account_login==payload.account_login, MT5Bridge.server_name==payload.server_name,
            MT5Bridge.status=='active')).all():
        old.status='revoked'
    raw=generate_code('BRIDGE'); bridge=MT5Bridge(id=uid(),user_id=intent.user_id,link_intent_id=intent.id,
        token_hash=hash_value(raw,pepper='bridge-token'),account_login=payload.account_login,server_name=payload.server_name)
    intent.claimed_at=now(); db.add(bridge); audit(db,'mt5_agent',bridge.id,'mt5.bridge_claimed','mt5_bridge',bridge.id); db.commit()
    return {'bridge_token':raw,'bridge_id':bridge.id,'api_base':settings.public_app_url.rstrip('/'),'warning':'احفظ الرمز في ملف إعدادات محلي آمن، ولن يظهر مرة أخرى.'}

@app.post('/api/mt5/deals', status_code=201)
async def ingest_closed_trade(payload: ClosedTradeIn, bridge_token: str = Header(default='', alias='X-Bridge-Token'), db: Session = Depends(get_db)):
    if not bridge_token: raise HTTPException(401,'رمز جسر MT5 مطلوب')
    bridge=db.scalar(select(MT5Bridge).where(MT5Bridge.token_hash==hash_value(bridge_token,pepper='bridge-token'),MT5Bridge.status=='active'))
    if not bridge: raise HTTPException(401,'رمز جسر MT5 غير صالح')
    existing=db.scalar(select(ClosedTrade).where(ClosedTrade.user_id==bridge.user_id,ClosedTrade.account_login==bridge.account_login,
        ClosedTrade.server_name==bridge.server_name,ClosedTrade.external_position_id==payload.external_position_id))
    if existing: return {'ok':True,'duplicate':True,'trade_id':existing.id,'performance_fee':float(existing.fee_amount)}
    net,fee=calculate_fee(payload.gross_profit,payload.swap,payload.commission, rate=0.30)
    try: closed_at=datetime.fromisoformat(payload.closed_at.replace('Z','+00:00'))
    except ValueError: raise HTTPException(422,'تاريخ إغلاق الصفقة غير صالح')
    if closed_at.tzinfo is None: closed_at=closed_at.replace(tzinfo=timezone.utc)
    if as_utc(closed_at) > now()+timedelta(minutes=5): raise HTTPException(422,'تاريخ إغلاق الصفقة يقع في المستقبل')
    if as_utc(closed_at) < as_utc(bridge.created_at):
        return {'ok':True,'ignored':True,'reason':'position_closed_before_account_link','performance_fee':0}
    trade=ClosedTrade(id=uid(),user_id=bridge.user_id,bridge_id=bridge.id,account_login=bridge.account_login,
        server_name=bridge.server_name,external_position_id=payload.external_position_id,
        symbol=payload.symbol,side=payload.side,volume=payload.volume,gross_profit=payload.gross_profit,swap=payload.swap,
        commission=payload.commission,net_profit=net,fee_rate=.30,fee_amount=fee,currency=payload.currency.upper(),closed_at=closed_at)
    db.add(trade); bridge.last_seen_at=now()
    if fee>0: db.add(PerformanceFee(id=uid(),user_id=bridge.user_id,trade_id=trade.id,amount=fee,currency=payload.currency.upper(),status='due'))
    audit(db,'mt5_agent',bridge.id,'trade.closed_reported','closed_trade',trade.id,{'net_profit':net,'fee_amount':fee,'currency':payload.currency})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing=db.scalar(select(ClosedTrade).where(ClosedTrade.user_id==bridge.user_id,ClosedTrade.account_login==bridge.account_login,
        ClosedTrade.server_name==bridge.server_name,ClosedTrade.external_position_id==payload.external_position_id))
        if existing:
            return {'ok':True,'duplicate':True,'trade_id':existing.id,'performance_fee':float(existing.fee_amount)}
        raise HTTPException(409,'تعارض في سجل الصفقة؛ أعد المحاولة بعد تحديث سجل الجسر')
    if fee>0:
        customer=db.get(User,bridge.user_id)
        await notify_admin(f'صفقة رابحة أُغلقت في بوت التداول الفائق\nالعميل: {customer.full_name if customer else bridge.user_id}\nالأداة: {payload.symbol}\nصافي الربح: {net:.2f} {payload.currency.upper()}\nعمولة الأداء 30% المستحقة: {fee:.2f} {payload.currency.upper()}')
    return {'ok':True,'duplicate':False,'trade_id':trade.id,'net_profit':net,'performance_fee':fee,'currency':payload.currency.upper(),'fee_status':'due' if fee>0 else 'none'}

@app.get('/api/mt5/status')
def mt5_status(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    rows=db.scalars(select(MT5Bridge).where(MT5Bridge.user_id==user.id,MT5Bridge.status=='active')).all()
    fresh=[r for r in rows if r.last_seen_at and as_utc(r.last_seen_at)>=now()-timedelta(minutes=2)]
    return {'connected':bool(fresh),'accounts':[{'login':r.account_login,'server':r.server_name,'last_seen_at':r.last_seen_at.isoformat() if r.last_seen_at else None,
             'online':bool(r.last_seen_at and as_utc(r.last_seen_at)>=now()-timedelta(minutes=2))} for r in rows]}

@app.post('/api/mt5/heartbeat')
def mt5_heartbeat(bridge_token: str = Header(default='', alias='X-Bridge-Token'), db: Session = Depends(get_db)):
    if not bridge_token: raise HTTPException(401,'Bridge token required')
    bridge=db.scalar(select(MT5Bridge).where(MT5Bridge.token_hash==hash_value(bridge_token,pepper='bridge-token'),MT5Bridge.status=='active'))
    if not bridge: raise HTTPException(401,'Invalid bridge token')
    bridge.last_seen_at=now(); db.commit()
    user=db.get(User,bridge.user_id)
    lic=db.scalar(select(License).where(License.user_id==bridge.user_id))
    licensed=bool(user and user.status=='active' and lic and lic.status=='active' and bridge.status=='active')
    consented=bool(user and user.auto_trading_enabled and user.trading_consent_at)
    live_consented=bool(user and user.live_trading_consent_at)
    demo_allowed=bool(licensed and consented)
    live_server_gate=bool(settings.live_trading_enabled and not settings.mt5_demo_only)
    live_allowed=bool(demo_allowed and live_consented and live_server_gate)
    return {'ok':True,'demo_execution_allowed':demo_allowed,'live_trading_allowed':live_allowed,
            'live_trading_enabled':live_server_gate,'live_customer_consented':live_consented,
            'license_active':licensed,'auto_trading_enabled':bool(user.auto_trading_enabled) if user else False}

@app.post('/api/mt5/signals', status_code=201)
def ingest_signal(payload: MarketSignalIn, bridge_token: str = Header(default='', alias='X-Bridge-Token'), db: Session = Depends(get_db)):
    if not bridge_token: raise HTTPException(401,'Bridge token required')
    bridge=db.scalar(select(MT5Bridge).where(MT5Bridge.token_hash==hash_value(bridge_token,pepper='bridge-token'),MT5Bridge.status=='active'))
    if not bridge: raise HTTPException(401,'Invalid bridge token')
    license_row=db.scalar(select(License).where(License.user_id==bridge.user_id,License.status=='active'))
    linked_user=db.get(User,bridge.user_id)
    if not license_row or not linked_user or linked_user.status!='active': raise HTTPException(403,'الترخيص أو الحساب غير نشط')
    payload=payload.model_dump()
    try: bar_time=datetime.fromisoformat(str(payload['bar_time']).replace('Z','+00:00'))
    except ValueError: raise HTTPException(422,'Invalid bar_time')
    if bar_time.tzinfo is None: bar_time=bar_time.replace(tzinfo=timezone.utc)
    if payload['direction']=='BUY' and not (payload['stop_loss'] < payload['entry_price'] < payload['take_profit']): raise HTTPException(422,'مستويات BUY غير منطقية')
    if payload['direction']=='SELL' and not (payload['take_profit'] < payload['entry_price'] < payload['stop_loss']): raise HTTPException(422,'مستويات SELL غير منطقية')
    signal=MarketSignal(id=uid(),user_id=bridge.user_id,bridge_id=bridge.id,symbol=str(payload['symbol'])[:40],
        timeframe=str(payload['timeframe'])[:12],direction=payload['direction'],confidence=float(payload['confidence']),
        entry_price=float(payload['entry_price']),stop_loss=float(payload['stop_loss']),take_profit=float(payload['take_profit']),
        strategy_votes=json.dumps(payload['strategy_votes'],ensure_ascii=False),bar_time=bar_time)
    try:
        db.add(signal); bridge.last_seen_at=now(); db.commit()
    except Exception:
        db.rollback()
        prior=db.scalar(select(MarketSignal).where(MarketSignal.bridge_id==bridge.id,MarketSignal.symbol==str(payload['symbol']),
           MarketSignal.timeframe==str(payload['timeframe']),MarketSignal.bar_time==bar_time))
        if prior: return {'ok':True,'duplicate':True,'signal_id':prior.id}
        raise
    return {'ok':True,'duplicate':False,'signal_id':signal.id}

@app.get('/api/customer/signals')
def customer_signals(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    rows=db.scalars(select(MarketSignal).where(MarketSignal.user_id==user.id).order_by(desc(MarketSignal.created_at)).limit(150)).all()
    return [{'id':s.id,'symbol':s.symbol,'timeframe':s.timeframe,'direction':s.direction,'confidence':s.confidence,
             'entry_price':s.entry_price,'stop_loss':s.stop_loss,'take_profit':s.take_profit,'strategy_votes':s.strategy_votes,
             'bar_time':s.bar_time.isoformat()} for s in rows]

@app.post('/api/customer/trading-settings')
def update_customer_trading_settings(payload: TradingSettingsIn, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    if payload.auto_trading_enabled and not payload.accept_risk_disclosure:
        raise HTTPException(400, 'يجب الموافقة الصريحة على بيان مخاطر التداول قبل تشغيل الإدارة التلقائية')
    if payload.live_trading_enabled and (not payload.auto_trading_enabled or not payload.accept_live_risk_disclosure):
        raise HTTPException(400, 'لتفعيل موافقة التداول الحقيقي يجب تشغيل الإدارة التلقائية والموافقة على بيان مخاطر الأموال الحقيقية')
    user.auto_trading_enabled=payload.auto_trading_enabled
    user.trading_consent_at=now() if payload.auto_trading_enabled and payload.accept_risk_disclosure else None
    user.live_trading_consent_at=now() if payload.live_trading_enabled and payload.accept_live_risk_disclosure else None
    audit(db,'customer',user.id,'trading.settings_updated','user',user.id,{
        'auto_trading_enabled':user.auto_trading_enabled,
        'live_trading_customer_consent':bool(user.live_trading_consent_at),
    })
    db.commit()
    live_server_gate=bool(settings.live_trading_enabled and not settings.mt5_demo_only)
    return {'ok':True,'auto_trading_enabled':user.auto_trading_enabled,
            'trading_consent_at':user.trading_consent_at.isoformat() if user.trading_consent_at else None,
            'live_trading_customer_consented':bool(user.live_trading_consent_at),
            'live_trading_consent_at':user.live_trading_consent_at.isoformat() if user.live_trading_consent_at else None,
            'live_server_gate_enabled':live_server_gate,
            'live_execution_available':bool(live_server_gate and user.auto_trading_enabled and user.live_trading_consent_at)}

@app.get('/api/customer/dashboard')
def customer_dashboard(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    trade_count=db.scalar(select(func.count(ClosedTrade.id)).where(ClosedTrade.user_id==user.id)) or 0
    winning=db.scalar(select(func.count(ClosedTrade.id)).where(ClosedTrade.user_id==user.id,ClosedTrade.net_profit>0)) or 0
    net_rows=db.execute(select(ClosedTrade.currency,func.sum(ClosedTrade.net_profit)).where(ClosedTrade.user_id==user.id).group_by(ClosedTrade.currency)).all()
    due=db.execute(select(PerformanceFee.currency,func.sum(PerformanceFee.amount)).where(PerformanceFee.user_id==user.id,PerformanceFee.status=='due').group_by(PerformanceFee.currency)).all()
    lic=user.license
    return {'trade_count':trade_count,'winning_trades':winning,'net_profit_by_currency':{c:float(v) for c,v in net_rows},
            'performance_fees_due':{c:float(v) for c,v in due},'license_status':lic.status if lic else None,
            'auto_trading_enabled':user.auto_trading_enabled,
            'live_trading_customer_consented':bool(user.live_trading_consent_at),
            'live_trading_server_gate_enabled':bool(settings.live_trading_enabled and not settings.mt5_demo_only),
            'mt5_connected':bool(db.scalar(select(func.count(MT5Bridge.id)).where(MT5Bridge.user_id==user.id,MT5Bridge.status=='active',MT5Bridge.last_seen_at>=now()-timedelta(minutes=2))))}

@app.get('/api/customer/trades')
def customer_trades(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    rows=db.scalars(select(ClosedTrade).where(ClosedTrade.user_id==user.id).order_by(desc(ClosedTrade.closed_at)).limit(300)).all()
    return [{'id':t.id,'position_id':t.external_position_id,'symbol':t.symbol,'side':t.side,'volume':t.volume,
             'net_profit':t.net_profit,'fee_amount':float(t.fee_amount),'currency':t.currency,'closed_at':t.closed_at.isoformat()} for t in rows]

@app.get('/api/customer/performance-fees')
def customer_fees(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    rows=db.scalars(select(PerformanceFee).where(PerformanceFee.user_id==user.id).order_by(desc(PerformanceFee.created_at)).limit(300)).all()
    return [{'id':f.id,'amount':float(f.amount),'currency':f.currency,'status':f.status,'paid_reference':f.paid_reference,'created_at':f.created_at.isoformat()} for f in rows]

# -------------------------- EXTERNAL INTELLIGENCE --------------------------
@app.get('/api/customer/assistant/status')
def customer_assistant_status(user: User = Depends(require_customer)):
    return {'available': settings.ai_chat_ready, 'mode': 'text',
            'message': 'المساعد جاهز' if settings.ai_chat_ready else 'المساعد يحتاج إعداد مزود الذكاء الاصطناعي على الخادم'}


@app.post('/api/customer/assistant/chat')
def customer_assistant_chat(payload: AssistantChatIn, request: Request,
                            user: User = Depends(require_customer), db: Session = Depends(get_db)):
    if not payload.consent_external_ai:
        raise HTTPException(400, 'يجب الموافقة أولًا على إرسال السؤال وملخص البيانات إلى مزود الذكاء الاصطناعي الخارجي.')
    if not settings.ai_chat_ready:
        raise HTTPException(503, 'المساعد الذكي غير مهيأ بعد. يلزم إعداد مزود النموذج على الخادم.')
    enforce_rate_limit(db, request, 'assistant_chat', user.id, limit=20, window_seconds=300, block_seconds=300)

    trade_count = db.scalar(select(func.count(ClosedTrade.id)).where(ClosedTrade.user_id == user.id)) or 0
    winning = db.scalar(select(func.count(ClosedTrade.id)).where(ClosedTrade.user_id == user.id, ClosedTrade.net_profit > 0)) or 0
    net_rows = db.execute(select(ClosedTrade.currency, func.sum(ClosedTrade.net_profit))
                          .where(ClosedTrade.user_id == user.id).group_by(ClosedTrade.currency)).all()
    recent_trades = db.scalars(select(ClosedTrade).where(ClosedTrade.user_id == user.id)
                               .order_by(desc(ClosedTrade.closed_at)).limit(8)).all()
    signals = db.scalars(select(MarketSignal).where(MarketSignal.user_id == user.id)
                         .order_by(desc(MarketSignal.created_at)).limit(5)).all()
    news_rows = db.execute(select(IntelligenceItem, IntegrationSource.name)
                           .join(IntegrationSource, IntegrationSource.id == IntelligenceItem.source_id)
                           .where(IntegrationSource.enabled.is_(True))
                           .order_by(desc(IntelligenceItem.published_at)).limit(10)).all()

    account_context = {
        'closed_trade_count': trade_count,
        'winning_trade_count': winning,
        'net_profit_by_currency': {currency: float(value or 0) for currency, value in net_rows},
        'recent_closed_trades': [{
            'symbol': trade.symbol, 'side': trade.side, 'volume': trade.volume,
            'net_profit': trade.net_profit, 'currency': trade.currency,
            'closed_at': trade.closed_at.isoformat(),
        } for trade in recent_trades],
        'recent_analysis_signals': [{
            'symbol': signal.symbol, 'timeframe': signal.timeframe,
            'direction': signal.direction, 'confidence': signal.confidence,
            'created_at': signal.created_at.isoformat(),
        } for signal in signals],
        'auto_trading_enabled': user.auto_trading_enabled,
        'live_trading_enabled_on_server': bool(settings.live_trading_enabled and not settings.mt5_demo_only),
    }
    news_context = [{
        'source': source_name, 'title': item.title, 'summary': item.summary[:1200],
        'url': item.url, 'published_at': item.published_at.isoformat(),
        'trust_status': item.trust_status,
    } for item, source_name in news_rows]

    try:
        answer = ask_model(question=payload.message,
                           history=[entry.model_dump() for entry in payload.history],
                           account_context=account_context, news_context=news_context)
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    sources = [{'name': source, 'title': item.title, 'url': item.url,
                'published_at': item.published_at.isoformat()}
               for item, source in news_rows if item.url]
    return {'answer': answer, 'sources': sources, 'can_trigger_trades': False}


@app.get('/api/customer/intelligence')
def customer_intelligence(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.execute(
        select(IntelligenceItem, IntegrationSource.name)
        .join(IntegrationSource, IntegrationSource.id == IntelligenceItem.source_id)
        .where(IntegrationSource.enabled.is_(True))
        .order_by(desc(IntelligenceItem.published_at), desc(IntelligenceItem.received_at))
        .limit(100)
    ).all()
    return [item_view(item, source_name) for item, source_name in rows]


@app.post('/api/integrations/webhook/{source_id}', status_code=202)
async def receive_bot_webhook(source_id: str, payload: IntelligenceWebhookIn, request: Request,
                              integration_token: str = Header(default='', alias='X-Integration-Token'),
                              db: Session = Depends(get_db)):
    if not integration_token:
        raise HTTPException(401, 'رمز تكامل البوت مطلوب')
    source = db.get(IntegrationSource, source_id)
    if not source or source.kind != 'webhook' or not source.enabled:
        raise HTTPException(404, 'مصدر التكامل غير متاح')
    if not source.token_hash or source.token_hash != hash_value(integration_token, pepper='integration-source'):
        raise HTTPException(401, 'رمز تكامل البوت غير صالح')
    enforce_rate_limit(db, request, 'integration_webhook', source.id, limit=120, window_seconds=60, block_seconds=120)
    try:
        item, duplicate = add_intelligence_item(
            db, source,
            external_id=payload.external_id or '',
            item_type=payload.item_type,
            title=payload.title,
            summary=payload.summary,
            url=payload.url,
            published_at=parse_datetime(payload.published_at),
            symbols=payload.symbols,
        )
        source.last_success_at = now()
        source.last_error = None
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    return {'ok': True, 'duplicate': duplicate, 'item_id': item.id,
            'trust_status': item.trust_status, 'can_trigger_trades': False}


@app.post('/api/integrations/telegram/{source_id}', status_code=202)
async def receive_telegram_update(source_id: str, request: Request,
                                  secret_token: str = Header(default='', alias='X-Telegram-Bot-Api-Secret-Token'),
                                  db: Session = Depends(get_db)):
    if not secret_token:
        raise HTTPException(401, 'Telegram webhook secret مطلوب')
    source = db.get(IntegrationSource, source_id)
    if not source or source.kind != 'telegram' or not source.enabled:
        raise HTTPException(404, 'مصدر Telegram غير متاح')
    if not source.token_hash or source.token_hash != hash_value(secret_token, pepper='integration-source'):
        raise HTTPException(401, 'Telegram webhook secret غير صالح')
    enforce_rate_limit(db, request, 'telegram_webhook', source.id, limit=120, window_seconds=60, block_seconds=120)
    body = await request.body()
    if len(body) > 256_000:
        raise HTTPException(413, 'حجم تحديث Telegram أكبر من الحد المسموح')
    try:
        update = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, 'تحديث Telegram غير صالح')
    # Only public channel posts are shared across customer workspaces. Private chats and
    # group messages are intentionally ignored to prevent accidental customer-data disclosure.
    message = update.get('channel_post') or update.get('edited_channel_post') or {}
    chat = message.get('chat') or {}
    channel_username = str(chat.get('username') or '').strip().lstrip('@')
    text_value = message.get('text') or message.get('caption') or ''
    if not text_value.strip() or not channel_username:
        return {'ok': True, 'ignored': True, 'reason': 'public_channel_post_required'}
    message_id = str(update.get('update_id') or message.get('message_id') or '')
    try:
        published_at = datetime.fromtimestamp(int(message.get('date')), timezone.utc) if message.get('date') else now()
    except (TypeError, ValueError, OverflowError, OSError):
        published_at = now()
    telegram_url = f"https://t.me/{channel_username}/{message.get('message_id')}" if message.get('message_id') else None
    try:
        item, duplicate = add_intelligence_item(
            db, source,
            external_id=message_id,
            item_type='bot_message',
            title=text_value[:300],
            summary=text_value,
            url=telegram_url,
            published_at=published_at,
            symbols=[],
        )
        source.last_success_at = now()
        source.last_error = None
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    return {'ok': True, 'duplicate': duplicate, 'item_id': item.id,
            'trust_status': item.trust_status, 'can_trigger_trades': False}


@app.get('/api/owner/integrations/sources')
def owner_integration_sources(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.scalars(select(IntegrationSource).order_by(desc(IntegrationSource.created_at))).all()
    return [{
        'id': row.id, 'name': row.name, 'kind': row.kind, 'url': row.url,
        'enabled': row.enabled, 'last_seen_at': row.last_seen_at.isoformat() if row.last_seen_at else None,
        'last_success_at': row.last_success_at.isoformat() if row.last_success_at else None,
        'last_error': row.last_error, 'created_at': row.created_at.isoformat(),
    } for row in rows]


@app.post('/api/owner/integrations/sources', status_code=201)
def owner_create_integration_source(payload: IntegrationSourceIn, owner: User = Depends(require_owner),
                                    db: Session = Depends(get_db)):
    if payload.kind == 'rss':
        if not payload.url:
            raise HTTPException(422, 'رابط RSS مطلوب')
        try:
            url = validate_feed_url_syntax(payload.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        token = None
    else:
        if payload.url:
            raise HTTPException(422, 'لا يلزم رابط عند استخدام Webhook أو Telegram')
        url = None
        token = secrets.token_urlsafe(32)
    source = IntegrationSource(
        id=uid(), name=payload.name, kind=payload.kind, url=url,
        token_hash=hash_value(token, pepper='integration-source') if token else None,
        enabled=True, created_by_id=owner.id,
    )
    db.add(source)
    audit(db, 'owner', owner.id, 'integration.source_created', 'integration_source', source.id,
          {'name': source.name, 'kind': source.kind})
    db.commit()
    result = {'id': source.id, 'name': source.name, 'kind': source.kind, 'enabled': source.enabled}
    if token:
        result['secret_once'] = token
        if source.kind == 'telegram':
            result['webhook_url'] = f"{settings.public_app_url.rstrip('/')}/api/integrations/telegram/{source.id}"
            result['secret_header'] = 'X-Telegram-Bot-Api-Secret-Token'
        else:
            result['webhook_url'] = f"{settings.public_app_url.rstrip('/')}/api/integrations/webhook/{source.id}"
            result['secret_header'] = 'X-Integration-Token'
    return result


@app.patch('/api/owner/integrations/sources/{source_id}')
def owner_update_integration_source(source_id: str, payload: IntegrationSourceEnabledIn,
                                    owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    source = db.get(IntegrationSource, source_id)
    if not source:
        raise HTTPException(404, 'مصدر التكامل غير موجود')
    source.enabled = payload.enabled
    audit(db, 'owner', owner.id, 'integration.source_updated', 'integration_source', source.id,
          {'enabled': source.enabled})
    db.commit()
    return {'ok': True, 'id': source.id, 'enabled': source.enabled}


@app.post('/api/owner/integrations/sources/{source_id}/poll')
def owner_poll_integration_source(source_id: str, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    source = db.get(IntegrationSource, source_id)
    if not source or source.kind != 'rss':
        raise HTTPException(404, 'مصدر RSS غير موجود')
    if not source.enabled:
        raise HTTPException(409, 'مصدر الأخبار معطل')
    result = poll_rss_source(db, source)
    audit(db, 'owner', owner.id, 'integration.rss_polled', 'integration_source', source.id, result)
    db.commit()
    return result


@app.get('/api/owner/integrations/diagnostics')
def owner_integration_diagnostics(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    sources = db.scalars(select(IntegrationSource).order_by(desc(IntegrationSource.created_at))).all()
    result = []
    for source in sources:
        count = db.scalar(select(func.count(IntelligenceItem.id)).where(
            IntelligenceItem.source_id == source.id
        )) or 0
        latest = db.scalar(select(IntelligenceItem).where(
            IntelligenceItem.source_id == source.id
        ).order_by(desc(IntelligenceItem.received_at)).limit(1))
        result.append({
            'id': source.id,
            'name': source.name,
            'kind': source.kind,
            'enabled': source.enabled,
            'items_received': int(count),
            'last_seen_at': source.last_seen_at.isoformat() if source.last_seen_at else None,
            'last_success_at': source.last_success_at.isoformat() if source.last_success_at else None,
            'last_error': source.last_error,
            'latest_title': latest.title if latest else None,
            'latest_received_at': latest.received_at.isoformat() if latest else None,
            'latest_trust_status': latest.trust_status if latest else None,
        })
    return {
        'polling_enabled': bool(getattr(app.state, 'news_polling_enabled', False)),
        'poll_interval_seconds': settings.news_poll_interval_seconds,
        'sources_total': len(sources),
        'sources_enabled': sum(1 for row in sources if row.enabled),
        'items_total': int(db.scalar(select(func.count(IntelligenceItem.id))) or 0),
        'sources': result,
        'note': 'استلام الخبر لا يعني صحة التوقع أو السماح بتنفيذ صفقة.',
    }


@app.post('/api/owner/integrations/sources/{source_id}/test')
def owner_test_integration_source(source_id: str, owner: User = Depends(require_owner),
                                  db: Session = Depends(get_db)):
    source = db.get(IntegrationSource, source_id)
    if not source:
        raise HTTPException(404, 'مصدر التكامل غير موجود')
    if not source.enabled:
        raise HTTPException(409, 'مصدر التكامل معطل')

    sample = None
    if source.kind == 'rss':
        try:
            checked = inspect_rss_source(source)
            sample = checked.get('sample')
            if not sample:
                raise ValueError('تم الاتصال بالمصدر، لكن لم يتم العثور على خبر داخل الموجز.')
        except ValueError as exc:
            source.last_error = str(exc)[:300]
            db.commit()
            raise HTTPException(502, str(exc))
    elif source.kind not in {'webhook', 'telegram'}:
        raise HTTPException(422, 'نوع المصدر غير مدعوم للاختبار')

    # A savepoint verifies that the same persistence path used by live ingestion
    # accepts the test event, then rolls it back so no fake news reaches customers.
    savepoint = db.begin_nested()
    try:
        if sample:
            event = {
                'external_id': sample.get('external_id') or f"test-{uid()}",
                'item_type': 'news',
                'title': sample['title'],
                'summary': sample.get('summary') or '',
                'url': sample.get('url'),
                'published_at': sample.get('published_at') or now(),
                'symbols': [],
            }
        else:
            event = {
                'external_id': f"diagnostic-{uid()}",
                'item_type': 'bot_message' if source.kind == 'telegram' else 'news',
                'title': 'SUPER TRADING BOT integration diagnostic event',
                'summary': 'Synthetic test event. Not a real market news item.',
                'url': None,
                'published_at': now(),
                'symbols': [],
            }
        item, duplicate = add_intelligence_item(db, source, **event)
        db.flush()
        savepoint.rollback()
        db.refresh(source)
    except Exception as exc:
        savepoint.rollback()
        db.refresh(source)
        logger.exception('Integration pipeline test failed for source %s', source.id)
        raise HTTPException(500, 'فشل اختبار مسار استقبال وحفظ الخبر محليًا.') from exc

    external_confirmed = source.last_seen_at is not None
    audit(db, 'owner', owner.id, 'integration.pipeline_tested', 'integration_source', source.id, {
        'kind': source.kind, 'local_pipeline_ok': True, 'external_delivery_seen_before': external_confirmed,
    })
    db.commit()
    return {
        'ok': True,
        'source_id': source.id,
        'kind': source.kind,
        'connection_ok': True if source.kind == 'rss' else None,
        'local_pipeline_ok': True,
        'external_delivery_confirmed': external_confirmed,
        'duplicate_sample': bool(duplicate),
        'sample_title': sample.get('title') if sample else 'اختبار داخلي اصطناعي',
        'message': (
            'نجح الاتصال بالموجز واختبار مسار الحفظ. لم يتم إنشاء خبر تجريبي دائم.'
            if source.kind == 'rss'
            else 'نجح اختبار المعالجة والحفظ المحلي. يلزم إرسال تحديث حقيقي من Webhook/Telegram لتأكيد الاتصال الخارجي.'
        ),
        'can_trigger_trades': False,
    }


# ----------------------------- OWNER CONSOLE -----------------------------
@app.post('/api/owner/login')
def owner_login(payload: AdminLoginIn, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(db, request, 'owner_login', str(payload.email), limit=5, window_seconds=900, block_seconds=1800)
    user=db.scalar(select(User).where(func.lower(User.email)==str(payload.email).lower(),User.role=='owner'))
    if not user or not verify_password(payload.password,user.password_hash) or user.status!='active': raise HTTPException(401,'بيانات دخول المالك غير صحيحة أو الحساب موقوف')
    token,expires=create_session(db,user,payload.device_id); audit(db,'owner',user.id,'owner.login'); db.commit()
    return {'access_token':token,'token_type':'bearer','expires_at':expires.isoformat(),'user':user_view(user)}

@app.get('/api/owner/dashboard')
def owner_dashboard(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    users_total=db.scalar(select(func.count(User.id)).where(User.role=='customer')) or 0
    active_users=db.scalar(select(func.count(User.id)).join(License,License.user_id==User.id).where(User.role=='customer',User.status=='active',License.status=='active')) or 0
    pending_requests=db.scalar(select(func.count(SubscriptionRequest.id)).where(SubscriptionRequest.status=='pending')) or 0
    approved_subscription_revenue=db.scalar(select(func.coalesce(func.sum(SubscriptionRequest.amount_usd),0)).where(SubscriptionRequest.status=='approved')) or 0
    due_rows=db.execute(select(PerformanceFee.currency,func.sum(PerformanceFee.amount)).where(PerformanceFee.status=='due').group_by(PerformanceFee.currency)).all()
    paid_rows=db.execute(select(PerformanceFee.currency,func.sum(PerformanceFee.amount)).where(PerformanceFee.status=='paid').group_by(PerformanceFee.currency)).all()
    live_consent_count=db.scalar(select(func.count(User.id)).where(User.role=='customer',User.live_trading_consent_at.is_not(None))) or 0
    live_gate=bool(settings.live_trading_enabled and not settings.mt5_demo_only)
    return {'users_total':users_total,'active_users':active_users,'pending_requests':pending_requests,
            'subscription_revenue_usd':float(approved_subscription_revenue),
            'performance_fees_due':{c:float(v) for c,v in due_rows},'performance_fees_collected':{c:float(v) for c,v in paid_rows},
            'live_trading_enabled':live_gate,'mt5_demo_only':settings.mt5_demo_only,
            'live_customer_consent_count':live_consent_count,
            'trading_mode':'live_gated' if live_gate else 'demo_only'}

@app.get('/api/owner/subscription-requests')
def owner_requests(status_filter: str='pending', owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    q=select(SubscriptionRequest,User).join(User,SubscriptionRequest.user_id==User.id).order_by(desc(SubscriptionRequest.created_at))
    if status_filter!='all': q=q.where(SubscriptionRequest.status==status_filter)
    return [{'id':r.id,'name':u.full_name,'email':u.email,'phone':u.phone,'amount_usd':r.amount_usd,'payment_method':r.payment_method,
             'payment_reference':r.payment_reference,'payment_proof_note':r.payment_proof_note,'status':r.status,
             'created_at':r.created_at.isoformat()} for r,u in db.execute(q).all()]

@app.post('/api/owner/subscription-requests/{request_id}/review')
async def review_request(request_id: str, payload: ReviewRequestIn, owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    req=db.get(SubscriptionRequest,request_id)
    if not req: raise HTTPException(404,'طلب الاشتراك غير موجود')
    if req.status!='pending': raise HTTPException(409,'تمت مراجعة هذا الطلب من قبل')
    user=db.get(User,req.user_id); req.reviewed_by=owner.id; req.reviewed_at=now(); req.admin_note=payload.note
    activation_code=None
    if payload.decision=='approve':
        req.status='approved'; user.status='paid_pending_activation'
        activation_code=generate_code('STB');
        lic=License(id=uid(),user_id=user.id,code_hash=hash_value(activation_code,pepper='license-code'),status='issued')
        db.add(lic)
        if not user.referral_code: user.referral_code=generate_code('REF').replace('-','')
        audit(db,'owner',owner.id,'subscription.approved','subscription_request',req.id,{'amount_usd':500})
    else:
        req.status='rejected'; user.status='pending_payment'; audit(db,'owner',owner.id,'subscription.rejected','subscription_request',req.id,{'note':payload.note})
    db.commit()
    if activation_code:
        await notify_admin(f'تم اعتماد اشتراك {user.full_name}\nالبريد: {user.email}\nتم إصدار رمز تفعيل. راجع لوحة المالك لاستلامه مرة واحدة.')
        return {'ok':True,'status':'approved','activation_code':activation_code,'customer_email':user.email,
                'referral_code':user.referral_code,'referral_url':f'{settings.public_app_url.rstrip("/")}/?ref={user.referral_code}',
                'message':'احفظ رمز التفعيل وأرسله للعميل عبر قناة آمنة. لن يُعرض مرة أخرى.'}
    return {'ok':True,'status':'rejected'}

@app.get('/api/owner/users')
def owner_users(owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    users=db.scalars(select(User).where(User.role=='customer').order_by(desc(User.created_at))).all()
    return [{'id':u.id,'full_name':u.full_name,'email':u.email,'status':u.status,'referral_code':u.referral_code,
             'created_at':u.created_at.isoformat(),'license_status':u.license.status if u.license else None,
             'device_label':u.license.device_label if u.license else None} for u in users]

@app.get('/api/owner/referrals')
def owner_referrals(owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    referrer=aliased(User)
    rows=db.execute(select(User,referrer).join(referrer,User.referred_by_user_id==referrer.id).order_by(desc(User.created_at))).all()
    return [{'referred_customer':u.full_name,'referred_email':u.email,'referred_status':u.status,
             'referrer_name':r.full_name,'referrer_email':r.email,'referral_code':r.referral_code,
             'referral_reward':0,'created_at':u.created_at.isoformat()} for u,r in rows]

@app.get('/api/owner/licenses')
def owner_licenses(owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    rows=db.execute(select(License,User).join(User,License.user_id==User.id).order_by(desc(License.created_at))).all()
    return [{'id':l.id,'user_id':u.id,'customer':u.full_name,'email':u.email,'status':l.status,'device_label':l.device_label,
             'activated_at':l.activated_at.isoformat() if l.activated_at else None,'suspended_until':l.suspended_until.isoformat() if l.suspended_until else None} for l,u in rows]

@app.post('/api/owner/licenses/{license_id}/suspend')
def suspend_license(license_id: str, payload: AdminNoteIn, owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    lic=db.get(License,license_id)
    if not lic: raise HTTPException(404,'الترخيص غير موجود')
    lic.status='suspended'; lic.suspended_until=None
    suspended_user=db.get(User,lic.user_id); suspended_user.auto_trading_enabled=False; suspended_user.trading_consent_at=None; suspended_user.live_trading_consent_at=None
    revoke_user_bridges(db, lic.user_id)
    for s in db.scalars(select(ApiSession).where(ApiSession.user_id==lic.user_id,ApiSession.revoked_at.is_(None))).all(): s.revoked_at=now()
    add_security_event(db,lic.user_id,lic.id,'owner_suspended_license',lic.device_hash,payload.note or 'Suspended by owner')
    audit(db,'owner',owner.id,'license.suspended','license',lic.id,{'note':payload.note}); db.commit(); return {'ok':True}

@app.post('/api/owner/licenses/{license_id}/release')
def release_license(license_id: str, payload: AdminNoteIn, owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    lic=db.get(License,license_id)
    if not lic: raise HTTPException(404,'الترخيص غير موجود')
    lic.status='active' if lic.device_hash else 'issued'; lic.suspended_until=None
    add_security_event(db,lic.user_id,lic.id,'owner_released_license',lic.device_hash,payload.note or 'Released by owner')
    audit(db,'owner',owner.id,'license.released','license',lic.id,{'note':payload.note}); db.commit(); return {'ok':True,'status':lic.status}

@app.post('/api/owner/licenses/{license_id}/regenerate-code')
def regenerate_license_code(license_id: str, payload: AdminNoteIn, owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    lic=db.get(License,license_id)
    if not lic: raise HTTPException(404,'الترخيص غير موجود')
    user=db.get(User,lic.user_id)
    raw=generate_code('STB')
    lic.code_hash=hash_value(raw,pepper='license-code')
    lic.device_hash=None; lic.device_label=None; lic.activated_at=None; lic.status='issued'; lic.suspended_until=None
    user.status='paid_pending_activation'; user.auto_trading_enabled=False; user.trading_consent_at=None; user.live_trading_consent_at=None
    revoke_user_bridges(db, user.id)
    for s in db.scalars(select(ApiSession).where(ApiSession.user_id==lic.user_id,ApiSession.revoked_at.is_(None))).all(): s.revoked_at=now()
    add_security_event(db,lic.user_id,lic.id,'owner_regenerated_license_code',None,payload.note or 'Owner regenerated the activation code')
    audit(db,'owner',owner.id,'license.code_regenerated','license',lic.id,{'note':payload.note})
    db.commit()
    return {'ok':True,'activation_code':raw,'message':'تم إصدار رمز جديد. سيظهر مرة واحدة فقط؛ أرسله للعميل عبر قناة آمنة.'}

@app.post('/api/owner/licenses/{license_id}/reset-device')
def reset_license_device(license_id: str, payload: AdminNoteIn, owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    lic=db.get(License,license_id)
    if not lic: raise HTTPException(404,'الترخيص غير موجود')
    lic.device_hash=None; lic.device_label=None; lic.activated_at=None; lic.status='issued'; lic.suspended_until=None
    user=db.get(User,lic.user_id); user.status='paid_pending_activation'; user.auto_trading_enabled=False; user.trading_consent_at=None; user.live_trading_consent_at=None
    revoke_user_bridges(db, user.id)
    for s in db.scalars(select(ApiSession).where(ApiSession.user_id==lic.user_id,ApiSession.revoked_at.is_(None))).all(): s.revoked_at=now()
    add_security_event(db,lic.user_id,lic.id,'owner_reset_device',None,payload.note or 'Device reset by owner')
    audit(db,'owner',owner.id,'license.device_reset','license',lic.id,{'note':payload.note}); db.commit(); return {'ok':True,'status':'issued'}

@app.get('/api/owner/performance-fees')
def owner_performance_fees(status_filter: str='due', owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    q=select(PerformanceFee,User,ClosedTrade).join(User,PerformanceFee.user_id==User.id).join(ClosedTrade,PerformanceFee.trade_id==ClosedTrade.id).order_by(desc(PerformanceFee.created_at))
    if status_filter!='all': q=q.where(PerformanceFee.status==status_filter)
    return [{'id':f.id,'customer':u.full_name,'email':u.email,'trade_id':t.external_position_id,'symbol':t.symbol,
             'net_profit':t.net_profit,'fee_amount':float(f.amount),'currency':f.currency,'status':f.status,
             'closed_at':t.closed_at.isoformat(),'paid_reference':f.paid_reference} for f,u,t in db.execute(q).all()]

@app.post('/api/owner/performance-fees/{fee_id}/mark-paid')
def mark_fee_paid(fee_id: str, payload: FeePaymentIn, owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    fee=db.get(PerformanceFee,fee_id)
    if not fee: raise HTTPException(404,'مستحق العمولة غير موجود')
    if fee.status=='paid': raise HTTPException(409,'تم تسجيل هذه العمولة كمدفوعة بالفعل')
    fee.status='paid'; fee.paid_reference=payload.payment_reference; fee.paid_at=now()
    audit(db,'owner',owner.id,'performance_fee.paid','performance_fee',fee.id,{'reference':payload.payment_reference}); db.commit(); return {'ok':True}

@app.get('/api/owner/security-events')
def owner_security_events(owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    rows=db.scalars(select(SecurityEvent).order_by(desc(SecurityEvent.created_at)).limit(300)).all()
    return [{'id':e.id,'user_id':e.user_id,'event_type':e.event_type,'device_hash':e.device_hash,'details':e.details,'created_at':e.created_at.isoformat()} for e in rows]

@app.get('/api/owner/audit-log')
def owner_audit_log(owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    rows=db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(500)).all()
    return [{'id':e.id,'actor_type':e.actor_type,'actor_id':e.actor_id,'action':e.action,'target_type':e.target_type,
             'target_id':e.target_id,'metadata':e.metadata_json,'created_at':e.created_at.isoformat()} for e in rows]

@app.get('/api/owner/export/revenue.csv')
def owner_revenue_csv(owner: User=Depends(require_owner), db: Session=Depends(get_db)):
    import csv, io
    from fastapi.responses import Response
    output=io.StringIO(newline='')
    writer=csv.writer(output,quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['type','customer','email','reference','currency','amount','status','created_at'])
    def safe_cell(value):
        value=str(value if value is not None else '')
        return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
    for r,u in db.execute(select(SubscriptionRequest,User).join(User,SubscriptionRequest.user_id==User.id).where(SubscriptionRequest.status=='approved')).all():
        writer.writerow(['subscription',safe_cell(u.full_name),safe_cell(u.email),r.id,'USD','500','paid',r.created_at.isoformat()])
    for f,u in db.execute(select(PerformanceFee,User).join(User,PerformanceFee.user_id==User.id)).all():
        writer.writerow(['performance_fee',safe_cell(u.full_name),safe_cell(u.email),f.id,f.currency,f'{float(f.amount):.2f}',f.status,f.created_at.isoformat()])
    return Response(output.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename="super-trading-revenue.csv"'})

@app.get('/')
def index(): return FileResponse(FRONTEND/'index.html')
app.mount('/static', StaticFiles(directory=FRONTEND), name='static')
app.mount('/owner-console/assets', StaticFiles(directory=OWNER_CONSOLE), name='owner-console-assets')
@app.get('/owner-console', include_in_schema=False)
def owner_console():
    return FileResponse(OWNER_CONSOLE/'owner.html', headers={'Cache-Control': 'no-store, private', 'X-Robots-Tag': 'noindex, nofollow'})

@app.get('/owner-console/', include_in_schema=False)
def owner_console_pwa():
    return FileResponse(OWNER_CONSOLE/'owner.html', headers={'Cache-Control':'no-store, private','X-Robots-Tag':'noindex, nofollow'})

@app.get('/owner-console/manifest.webmanifest', include_in_schema=False)
def owner_console_manifest():
    return FileResponse(OWNER_CONSOLE/'manifest.webmanifest', media_type='application/manifest+json', headers={'Cache-Control':'no-cache','X-Robots-Tag':'noindex, nofollow'})

@app.get('/owner-console/sw.js', include_in_schema=False)
def owner_console_service_worker():
    return FileResponse(OWNER_CONSOLE/'sw.js', media_type='application/javascript', headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/owner-console/','X-Robots-Tag':'noindex, nofollow'})

@app.get('/owner-console/app.js', include_in_schema=False)
def owner_console_script():
    return FileResponse(OWNER_CONSOLE/'owner.js', media_type='application/javascript', headers={'Cache-Control': 'no-store, private', 'X-Robots-Tag': 'noindex, nofollow'})

@app.get('/manifest.webmanifest')
def manifest(): return FileResponse(FRONTEND/'manifest.webmanifest',media_type='application/manifest+json')
@app.get('/sw.js')
def service_worker(): return FileResponse(FRONTEND/'sw.js',media_type='application/javascript')
