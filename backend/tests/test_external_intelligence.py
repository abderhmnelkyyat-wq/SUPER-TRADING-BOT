from datetime import datetime, timezone
import json

from app.db import SessionLocal
from app.models import User
from app.security import uid, hash_password


def headers(token):
    return {'Authorization': f'Bearer {token}'}


def create_customer(client, owner_token, email='intel-customer@test.example'):
    created = client.post('/api/public/subscriptions', json={
        'full_name': 'Intelligence Customer', 'email': email, 'phone': '+201000000001',
        'payment_method': 'Bank transfer', 'payment_reference': 'INTEL-' + email.split('@')[0],
    })
    assert created.status_code == 201, created.text
    request_id = created.json()['request_id']
    approved = client.post(f'/api/owner/subscription-requests/{request_id}/review',
                           headers=headers(owner_token), json={'decision': 'approve'})
    assert approved.status_code == 200, approved.text
    activated = client.post('/api/auth/activate', json={
        'email': email, 'activation_code': approved.json()['activation_code'],
        'password': 'CustomerStrongPassword!2026', 'device_id': 'z' * 48,
    })
    assert activated.status_code == 200, activated.text
    return activated.json()['access_token']


def test_customer_cannot_manage_external_sources(client, owner_token):
    customer_token = create_customer(client, owner_token)
    denied = client.post('/api/owner/integrations/sources', headers=headers(customer_token), json={
        'name': 'Unauthorized', 'kind': 'webhook'
    })
    assert denied.status_code == 403
    assert client.get('/api/owner/integrations/sources', headers=headers(customer_token)).status_code == 403


def test_webhook_ingestion_is_authenticated_deduplicated_and_customer_visible(client, owner_token):
    created = client.post('/api/owner/integrations/sources', headers=headers(owner_token), json={
        'name': 'External Research Bot', 'kind': 'webhook'
    })
    assert created.status_code == 201, created.text
    data = created.json()
    token = data['secret_once']
    source_id = data['id']
    customer_token = create_customer(client, owner_token)

    invalid = client.post(f"/api/integrations/webhook/{source_id}", json={'title': 'A news item'})
    assert invalid.status_code == 401

    payload = {
        'external_id': 'news-100', 'item_type': 'market_event',
        'title': '<b>Central bank update</b>',
        'summary': '<p>Policy statement published.</p>',
        'url': 'https://example.com/news/100',
        'published_at': '2026-11-16T12:00:00Z', 'symbols': ['EURUSD', 'XAUUSD'],
    }
    auth = {'X-Integration-Token': token}
    first = client.post(f"/api/integrations/webhook/{source_id}", headers=auth, json=payload)
    assert first.status_code == 202, first.text
    assert first.json()['can_trigger_trades'] is False
    second = client.post(f"/api/integrations/webhook/{source_id}", headers=auth, json=payload)
    assert second.status_code == 202 and second.json()['duplicate'] is True

    visible = client.get('/api/customer/intelligence', headers=headers(customer_token))
    assert visible.status_code == 200
    assert len(visible.json()) == 1
    item = visible.json()[0]
    assert item['title'] == 'Central bank update'
    assert item['trust_status'] == 'unverified_external'
    assert item['can_trigger_trades'] is False
    assert item['symbols'] == ['EURUSD', 'XAUUSD']

    owner_list = client.get('/api/owner/integrations/sources', headers=headers(owner_token))
    assert owner_list.status_code == 200 and len(owner_list.json()) == 1
    assert 'token_hash' not in owner_list.text and token not in owner_list.text


def test_telegram_webhook_validates_secret_and_normalizes_message(client, owner_token):
    created = client.post('/api/owner/integrations/sources', headers=headers(owner_token), json={
        'name': 'My Telegram Bot', 'kind': 'telegram'
    })
    assert created.status_code == 201, created.text
    data = created.json()
    assert data['webhook_url'].endswith('/api/integrations/telegram/' + data['id'])
    payload = {'update_id': 4455, 'channel_post': {'message_id': 99, 'date': 1794859200, 'text': 'Gold market bulletin', 'chat': {'type': 'channel', 'username': 'public_markets'}}}
    bad = client.post(f"/api/integrations/telegram/{data['id']}", json=payload)
    assert bad.status_code == 401
    good = client.post(f"/api/integrations/telegram/{data['id']}",
                       headers={'X-Telegram-Bot-Api-Secret-Token': data['secret_once']}, json=payload)
    assert good.status_code == 202, good.text
    assert good.json()['can_trigger_trades'] is False
    assert client.get('/api/owner/integrations/sources', headers=headers(owner_token)).json()[0]['kind'] == 'telegram'


def test_telegram_private_or_group_messages_are_not_shared(client, owner_token):
    created = client.post('/api/owner/integrations/sources', headers=headers(owner_token), json={
        'name': 'Telegram Public Feed', 'kind': 'telegram'
    }).json()
    payload = {'update_id': 991, 'message': {'message_id': 5, 'text': 'private account details'}}
    response = client.post(f"/api/integrations/telegram/{created['id']}",
                           headers={'X-Telegram-Bot-Api-Secret-Token': created['secret_once']}, json=payload)
    assert response.status_code == 202 and response.json()['ignored'] is True
    assert client.get('/api/owner/integrations/sources', headers=headers(owner_token)).status_code == 200


def test_rss_source_rejects_http_private_hosts_and_custom_ports(client, owner_token):
    for url in ['http://example.com/rss.xml', 'https://localhost/feed.xml', 'https://example.com:8443/feed.xml']:
        result = client.post('/api/owner/integrations/sources', headers=headers(owner_token), json={
            'name': 'Invalid feed', 'kind': 'rss', 'url': url
        })
        assert result.status_code == 422, (url, result.text)


def test_owner_cannot_use_customer_login_or_activation_endpoints(client):
    login = client.post('/api/auth/login', json={
        'email': 'owner@test.example', 'password': 'OwnerStrongPass!2026', 'device_id': 'o' * 48
    })
    assert login.status_code == 401
    activation = client.post('/api/auth/activate', json={
        'email': 'owner@test.example', 'activation_code': 'X' * 30,
        'password': 'OwnerStrongPass!2026', 'device_id': 'p' * 48
    })
    assert activation.status_code == 403


def test_database_rejects_a_second_owner(client):
    from sqlalchemy.exc import IntegrityError
    db = SessionLocal()
    try:
        db.add(User(id=uid(), full_name='Second owner', email='second-owner@test.example',
                    password_hash=hash_password('OwnerStrongPassword!2026'), role='owner', status='active'))
        try:
            db.commit()
            assert False, 'The single-owner database index should reject a second owner.'
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_rss_poll_creates_normalized_news_and_deduplicates(client, owner_token, monkeypatch):
    from app.db import SessionLocal
    from app.models import IntegrationSource
    from app.integrations import news

    created = client.post('/api/owner/integrations/sources', headers=headers(owner_token), json={
        'name': 'Sample RSS', 'kind': 'rss', 'url': 'https://news.example/feed.xml'
    })
    assert created.status_code == 201, created.text
    source_id = created.json()['id']
    sample = b'''<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Market bulletin</title><description><![CDATA[<p>Rates update</p>]]></description>
      <link>https://news.example/story/1</link><guid>story-1</guid>
      <pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>'''
    monkeypatch.setattr(news, '_download_feed', lambda url: sample)
    db = SessionLocal()
    try:
        source = db.get(IntegrationSource, source_id)
        first = news.poll_rss_source(db, source)
        second = news.poll_rss_source(db, source)
    finally:
        db.close()
    assert first['ok'] is True and first['inserted'] == 1
    assert second['ok'] is True and second['inserted'] == 0 and second['duplicates'] == 1
    customer_token = create_customer(client, owner_token, email='rss-customer@test.example')
    rows = client.get('/api/customer/intelligence', headers=headers(customer_token)).json()
    assert len(rows) == 1
    assert rows[0]['title'] == 'Market bulletin'
    assert rows[0]['summary'] == 'Rates update'


def test_session_must_belong_to_token_subject(client):
    from app.db import SessionLocal
    from app.models import ApiSession, User
    from app.security import hash_value, issue_token
    from app.services import as_utc
    from sqlalchemy import select

    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.email == 'owner@test.example'))
        victim = User(id=uid(), full_name='Token Subject', email='token-subject@test.example',
                      password_hash=hash_password('CustomerStrongPassword!2026'), role='customer', status='active')
        db.add(victim)
        session_id = uid()
        device_hash = 'd' * 64
        token, expires = issue_token(victim.id, 'customer', session_id, device_hash)
        db.add(ApiSession(id=session_id, user_id=owner.id, token_hash=hash_value(token, pepper='session-token'),
                          device_hash=device_hash, expires_at=expires))
        db.commit()
    finally:
        db.close()
    response = client.get('/api/customer/intelligence', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 401


def test_owner_console_assets_are_not_exposed_by_public_static_mount(client):
    public_page = client.get('/')
    assert public_page.status_code == 200
    assert 'ownerLoginForm' not in public_page.text
    assert 'ownerApp' not in public_page.text
    assert client.get('/static/owner.html').status_code == 404
    assert client.get('/static/owner.js').status_code == 404
    private_page = client.get('/owner-console')
    assert private_page.status_code == 200
    assert 'ownerLoginForm' in private_page.text
    private_script = client.get('/owner-console/app.js')
    assert private_script.status_code == 200
    assert 'api/owner/login' in private_script.text


def test_assistant_is_disabled_without_provider_settings(client, owner_token):
    customer_token = create_customer(client, owner_token, email='assistant-disabled@test.example')
    status = client.get('/api/customer/assistant/status', headers=headers(customer_token))
    assert status.status_code == 200 and status.json()['available'] is False
    response = client.post('/api/customer/assistant/chat', headers=headers(customer_token), json={'message': 'حلل السوق', 'consent_external_ai': True})
    assert response.status_code == 503


def test_assistant_uses_only_customer_scoped_context_and_untrusted_news(client, owner_token, monkeypatch):
    from types import SimpleNamespace
    import app.main as main_module
    import app.integrations.assistant as assistant_module
    from app.models import IntegrationSource
    from app.integrations.intelligence import add_intelligence_item
    from app.security import uid
    from app.db import SessionLocal

    customer_token = create_customer(client, owner_token, email='assistant-enabled@test.example')
    db = SessionLocal()
    source = IntegrationSource(id=uid(), name='Test Public News', kind='webhook', enabled=True)
    db.add(source); db.flush()
    add_intelligence_item(db, source, external_id='assistant-news-1', item_type='news',
                          title='Central bank statement', summary='Rates remain unchanged.',
                          url='https://example.com/statement')
    db.commit(); db.close()

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {'choices': [{'message': {'content': 'هذا شرح تجريبي للخبر وبيانات حسابك.'}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.payload = None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, url, headers, json):
            captured['url'] = url
            captured['headers'] = headers
            captured['payload'] = json
            return FakeResponse()

    captured = {}
    fake_settings = SimpleNamespace(ai_chat_ready=True,
                                    ai_chat_api_url='https://ai.example/v1/chat/completions',
                                    ai_chat_api_key='test-secret-not-real', ai_chat_model='test-model')
    monkeypatch.setattr(main_module, 'settings', SimpleNamespace(ai_chat_ready=True,
                                                                  live_trading_enabled=False, mt5_demo_only=True))
    monkeypatch.setattr(assistant_module, 'settings', fake_settings)
    monkeypatch.setattr(assistant_module.httpx, 'Client', FakeClient)

    no_consent = client.post('/api/customer/assistant/chat', headers=headers(customer_token), json={'message': 'اشرح لي آخر خبر'})
    assert no_consent.status_code == 400
    assert not captured

    response = client.post('/api/customer/assistant/chat', headers=headers(customer_token), json={
        'message': 'اشرح لي آخر خبر',
        'history': [{'role': 'user', 'content': 'ما الأخبار؟'}, {'role': 'assistant', 'content': 'لا توجد بيانات بعد.'}],
        'consent_external_ai': True,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['answer'] == 'هذا شرح تجريبي للخبر وبيانات حسابك.'
    assert data['can_trigger_trades'] is False
    assert data['sources'][0]['name'] == 'Test Public News'
    system_message = captured['payload']['messages'][0]['content']
    assert 'بيانات غير موثوقة' in system_message
    assert 'Central bank statement' in system_message
    assert captured['payload']['messages'][-1]['content'] == 'اشرح لي آخر خبر'
    assert captured['headers']['Authorization'] == 'Bearer test-secret-not-real'


def test_assistant_rejects_non_https_provider_endpoint(monkeypatch):
    from types import SimpleNamespace
    import pytest
    import app.integrations.assistant as assistant_module
    monkeypatch.setattr(assistant_module, 'settings', SimpleNamespace(
        ai_chat_ready=True, ai_chat_api_url='http://ai.example/chat',
        ai_chat_api_key='x', ai_chat_model='test'))
    with pytest.raises(ValueError):
        assistant_module.ask_model(question='test', history=[], account_context={}, news_context=[])
