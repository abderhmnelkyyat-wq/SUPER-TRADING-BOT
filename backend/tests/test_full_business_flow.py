from datetime import datetime, timezone, timedelta

def close_time(): return (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()

def headers(token): return {'Authorization':f'Bearer {token}'}

def create_paid_customer(client, owner_token, email='customer@test.example'):
    r=client.post('/api/public/subscriptions',json={'full_name':'Test Customer','email':email,'phone':'+201000000000',
      'payment_method':'Bank transfer','payment_reference':'TXN-'+email.split('@')[0], 'payment_proof_note':'Transfer screenshot sent securely'})
    assert r.status_code==201,r.text
    request_id=r.json()['request_id']
    approved=client.post(f'/api/owner/subscription-requests/{request_id}/review',headers=headers(owner_token),json={'decision':'approve','note':'Payment verified'})
    assert approved.status_code==200,approved.text
    return approved.json()['activation_code'], approved.json()

def test_subscription_approval_activation_and_referral(client,owner_token):
    code,approved=create_paid_customer(client,owner_token)
    assert approved['referral_code'] and 'localhost' not in approved['referral_url']
    a=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'b'*48,'device_label':'Windows Desktop'})
    assert a.status_code==200,a.text
    token=a.json()['access_token']
    account=client.get('/api/account',headers=headers(token))
    assert account.status_code==200
    assert account.json()['status']=='active'
    referral=client.get('/api/referral',headers=headers(token))
    assert referral.status_code==200 and referral.json()['reward_usd']==0
    dash=client.get('/api/owner/dashboard',headers=headers(owner_token))
    assert dash.json()['subscription_revenue_usd']==500.0

def test_duplicate_device_attempt_suspends_only_license(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    ok=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'c'*48,'device_label':'Original'})
    assert ok.status_code==200
    duplicate=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'d'*48,'device_label':'Unapproved'})
    assert duplicate.status_code==423
    lic=client.get('/api/owner/licenses',headers=headers(owner_token)).json()[0]
    assert lic['status']=='suspended'
    events=client.get('/api/owner/security-events',headers=headers(owner_token)).json()
    assert any(e['event_type']=='duplicate_device_activation' for e in events)

def test_mt5_closed_position_fee_is_exactly_15_percent_and_idempotent(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    activated=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'e'*48,'device_label':'Windows'})
    token=activated.json()['access_token']
    intent=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'12345678','server_name':'Broker-Demo'})
    assert intent.status_code==200,intent.text
    claim=client.post('/api/mt5/claim',json={'link_code':intent.json()['link_code'],'account_login':'12345678','server_name':'Broker-Demo'})
    assert claim.status_code==200,claim.text
    bridge=claim.json()['bridge_token']
    payload={'external_position_id':'POSITION-123','symbol':'EURUSD','side':'BUY','volume':0.1,
      'gross_profit':100,'swap':-2,'commission':-3,'currency':'USD','closed_at':close_time()}
    first=client.post('/api/mt5/deals',headers={'X-Bridge-Token':bridge},json=payload)
    assert first.status_code==201,first.text
    assert first.json()['net_profit']==95.0
    assert first.json()['performance_fee']==14.25
    second=client.post('/api/mt5/deals',headers={'X-Bridge-Token':bridge},json=payload)
    assert second.status_code==201 and second.json()['duplicate'] is True
    fees=client.get('/api/owner/performance-fees',headers=headers(owner_token)).json()
    assert len(fees)==1 and fees[0]['fee_amount']==14.25

def test_lossing_trade_does_not_create_performance_fee(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    activated=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'f'*48,'device_label':'Windows'})
    token=activated.json()['access_token']
    intent=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'87654321','server_name':'Broker-Demo'})
    bridge=client.post('/api/mt5/claim',json={'link_code':intent.json()['link_code'],'account_login':'87654321','server_name':'Broker-Demo'}).json()['bridge_token']
    payload={'external_position_id':'POSITION-LOSS','symbol':'GBPUSD','side':'SELL','volume':0.1,
      'gross_profit':-50,'swap':-1,'commission':-2,'currency':'USD','closed_at':close_time()}
    r=client.post('/api/mt5/deals',headers={'X-Bridge-Token':bridge},json=payload)
    assert r.status_code==201 and r.json()['performance_fee']==0
    fees=client.get('/api/owner/performance-fees',headers=headers(owner_token)).json()
    assert fees==[]

def test_customer_cannot_access_owner_console(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    a=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'g'*48,'device_label':'Android'})
    r=client.get('/api/owner/dashboard',headers=headers(a.json()['access_token']))
    assert r.status_code==403

def test_reject_wrong_mt5_account_on_claim(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    a=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'h'*48,'device_label':'Windows'})
    link=client.post('/api/mt5/link',headers=headers(a.json()['access_token']),json={'account_login':'12345678','server_name':'Broker-Demo'}).json()
    claim=client.post('/api/mt5/claim',json={'link_code':link['link_code'],'account_login':'12345678','server_name':'Other-Server'})
    assert claim.status_code==403

def test_owner_must_release_suspended_license(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    ok=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'i'*48,'device_label':'Primary'})
    assert ok.status_code==200
    bad=client.post('/api/auth/login',json={'email':'customer@test.example','password':'CustomerStrongPassword!2026',
      'device_id':'j'*48,'device_label':'Secondary'})
    assert bad.status_code==423
    lic=client.get('/api/owner/licenses',headers=headers(owner_token)).json()[0]
    # Even after the temporary lock time has passed, the owner must explicitly release it.
    import time
    time.sleep(0.01)
    still_locked=client.post('/api/auth/login',json={'email':'customer@test.example','password':'CustomerStrongPassword!2026',
      'device_id':'i'*48,'device_label':'Primary'})
    assert still_locked.status_code==423
    released=client.post(f"/api/owner/licenses/{lic['id']}/release",headers=headers(owner_token),json={'note':'Reviewed; original device permitted'})
    assert released.status_code==200
    recovered=client.post('/api/auth/login',json={'email':'customer@test.example','password':'CustomerStrongPassword!2026',
      'device_id':'i'*48,'device_label':'Primary'})
    assert recovered.status_code==200

def test_live_policy_requires_separate_customer_consent_and_owner_server_enable(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    activated=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'k'*48,'device_label':'Windows'})
    token=activated.json()['access_token']
    missing_live_disclosure=client.post('/api/customer/trading-settings',headers=headers(token),json={
      'auto_trading_enabled':True,'accept_risk_disclosure':True,'live_trading_enabled':True,
      'accept_live_risk_disclosure':False})
    assert missing_live_disclosure.status_code==400
    saved=client.post('/api/customer/trading-settings',headers=headers(token),json={
      'auto_trading_enabled':True,'accept_risk_disclosure':True,'live_trading_enabled':True,
      'accept_live_risk_disclosure':True})
    assert saved.status_code==200 and saved.json()['live_trading_customer_consented'] is True
    link=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'11122233','server_name':'Broker-Demo'}).json()
    bridge=client.post('/api/mt5/claim',json={'link_code':link['link_code'],'account_login':'11122233','server_name':'Broker-Demo'}).json()['bridge_token']
    policy=client.post('/api/mt5/heartbeat',headers={'X-Bridge-Token':bridge}).json()
    assert policy['live_customer_consented'] is True
    assert policy['live_trading_allowed'] is False  # owner/server gate is deliberately OFF in test config
    disabled=client.post('/api/customer/trading-settings',headers=headers(token),json={
      'auto_trading_enabled':False,'accept_risk_disclosure':False,'live_trading_enabled':False,
      'accept_live_risk_disclosure':False})
    assert disabled.status_code==200 and disabled.json()['live_trading_customer_consented'] is False
    policy_after_disable=client.post('/api/mt5/heartbeat',headers={'X-Bridge-Token':bridge}).json()
    assert policy_after_disable['live_trading_allowed'] is False
    rejected=client.post('/api/customer/trading-settings',headers=headers(token),json={'auto_trading_enabled':True,'accept_risk_disclosure':False})
    assert rejected.status_code==400

def test_subscription_payment_reference_cannot_be_reused(client):
    first=client.post('/api/public/subscriptions',json={'full_name':'First Buyer','email':'first@example.com',
      'payment_method':'Bank transfer','payment_reference':'SAME-REFERENCE-001'})
    assert first.status_code==201,first.text
    second=client.post('/api/public/subscriptions',json={'full_name':'Second Buyer','email':'second@example.com',
      'payment_method':'bank transfer','payment_reference':'same-reference-001'})
    assert second.status_code==409


def test_authentication_rate_limit_is_persistent(client):
    body={'email':'unknown@example.com','password':'BadPassword!2026','device_id':'z'*48}
    results=[client.post('/api/auth/login',json=body) for _ in range(8)]
    assert all(r.status_code==401 for r in results)
    blocked=client.post('/api/auth/login',json=body)
    assert blocked.status_code==429


def test_device_mismatch_revokes_the_existing_mt5_bridge(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    activated=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'q'*48,'device_label':'Primary'})
    assert activated.status_code==200
    token=activated.json()['access_token']
    link=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'56781234','server_name':'Broker-Demo'})
    assert link.status_code==200
    bridge=client.post('/api/mt5/claim',json={'link_code':link.json()['link_code'],
      'account_login':'56781234','server_name':'Broker-Demo'}).json()['bridge_token']
    bad=client.post('/api/auth/login',json={'email':'customer@test.example','password':'CustomerStrongPassword!2026',
      'device_id':'r'*48})
    assert bad.status_code==423
    heartbeat=client.post('/api/mt5/heartbeat',headers={'X-Bridge-Token':bridge})
    assert heartbeat.status_code==401


def test_owner_suspended_account_cannot_login(client):
    from app.db import SessionLocal
    from app.models import User
    db=SessionLocal()
    try:
        owner=db.query(User).filter(User.email=='owner@test.example').one()
        owner.status='suspended'
        db.commit()
    finally:
        db.close()
    result=client.post('/api/owner/login',json={'email':'owner@test.example',
      'password':'OwnerStrongPass!2026','device_id':'a'*48})
    assert result.status_code==401


def test_same_closed_position_is_not_charged_again_after_bridge_relink(client,owner_token):
    code,_=create_paid_customer(client,owner_token)
    activated=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'s'*48,'device_label':'Desktop'})
    token=activated.json()['access_token']
    link1=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'99887766','server_name':'Broker-Demo'}).json()
    bridge1=client.post('/api/mt5/claim',json={'link_code':link1['link_code'],'account_login':'99887766','server_name':'Broker-Demo'}).json()['bridge_token']
    payload={'external_position_id':'SAME-POSITION-700','symbol':'XAUUSD','side':'BUY','volume':0.1,
      'gross_profit':100,'swap':0,'commission':0,'currency':'USD','closed_at':close_time()}
    first=client.post('/api/mt5/deals',headers={'X-Bridge-Token':bridge1},json=payload)
    assert first.status_code==201 and first.json()['performance_fee']==15.0
    link2=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'99887766','server_name':'Broker-Demo'}).json()
    bridge2=client.post('/api/mt5/claim',json={'link_code':link2['link_code'],'account_login':'99887766','server_name':'Broker-Demo'}).json()['bridge_token']
    duplicate=client.post('/api/mt5/deals',headers={'X-Bridge-Token':bridge2},json=payload)
    assert duplicate.status_code==201 and duplicate.json()['duplicate'] is True
    fees=client.get('/api/owner/performance-fees',headers=headers(owner_token)).json()
    assert len(fees)==1


def test_mt5_account_cannot_be_linked_to_two_customer_licenses(client,owner_token):
    # Customer one is created and links the account.
    code,_=create_paid_customer(client,owner_token,'first-mt5@example.com')
    first=client.post('/api/auth/activate',json={'email':'first-mt5@example.com','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'t'*48,'device_label':'Desktop'})
    token1=first.json()['access_token']
    link1=client.post('/api/mt5/link',headers=headers(token1),json={'account_login':'44556677','server_name':'Broker-Demo'}).json()
    claim1=client.post('/api/mt5/claim',json={'link_code':link1['link_code'],'account_login':'44556677','server_name':'Broker-Demo'})
    assert claim1.status_code==200
    # Customer two cannot attach the same broker account to another license.
    code2,_=create_paid_customer(client,owner_token,'second-mt5@example.com')
    second=client.post('/api/auth/activate',json={'email':'second-mt5@example.com','activation_code':code2,
      'password':'CustomerStrongPassword!2026','device_id':'u'*48,'device_label':'Desktop'})
    token2=second.json()['access_token']
    link2=client.post('/api/mt5/link',headers=headers(token2),json={'account_login':'44556677','server_name':'Broker-Demo'}).json()
    claim2=client.post('/api/mt5/claim',json={'link_code':link2['link_code'],'account_login':'44556677','server_name':'Broker-Demo'})
    assert claim2.status_code==409


def test_live_heartbeat_only_unlocks_after_all_customer_and_server_permissions(client,owner_token):
    from app.config import settings
    code,_=create_paid_customer(client,owner_token)
    activated=client.post('/api/auth/activate',json={'email':'customer@test.example','activation_code':code,
      'password':'CustomerStrongPassword!2026','device_id':'v'*48,'device_label':'Windows'})
    token=activated.json()['access_token']
    saved=client.post('/api/customer/trading-settings',headers=headers(token),json={
      'auto_trading_enabled':True,'accept_risk_disclosure':True,'live_trading_enabled':True,
      'accept_live_risk_disclosure':True})
    assert saved.status_code==200
    link=client.post('/api/mt5/link',headers=headers(token),json={'account_login':'22223333','server_name':'Broker-Real'}).json()
    bridge=client.post('/api/mt5/claim',json={'link_code':link['link_code'],'account_login':'22223333','server_name':'Broker-Real'}).json()['bridge_token']
    original_live=settings.live_trading_enabled
    original_demo=settings.mt5_demo_only
    try:
      object.__setattr__(settings,'live_trading_enabled',True)
      object.__setattr__(settings,'mt5_demo_only',False)
      policy=client.post('/api/mt5/heartbeat',headers={'X-Bridge-Token':bridge}).json()
      assert policy['live_trading_allowed'] is True
    finally:
      object.__setattr__(settings,'live_trading_enabled',original_live)
      object.__setattr__(settings,'mt5_demo_only',original_demo)
