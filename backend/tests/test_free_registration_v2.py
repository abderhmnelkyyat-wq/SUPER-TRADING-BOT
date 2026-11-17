from app.services import calculate_fee


def test_free_registration_creates_active_customer_and_device_license(client):
    response = client.post('/api/auth/register', json={
        'full_name': 'Free Test Customer',
        'email': 'free-customer@test.example',
        'phone': '+201000000001',
        'password': 'CustomerStrongPassword!2026',
        'device_id': 'f' * 48,
        'device_label': 'Android Test Device',
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert data['plan'] == 'free'
    assert data['performance_fee_rate'] == 0.30
    assert data['user']['status'] == 'active'
    assert data['user']['license_status'] == 'active'
    account = client.get('/api/account', headers={'Authorization': f"Bearer {data['access_token']}"})
    assert account.status_code == 200
    assert account.json()['email'] == 'free-customer@test.example'


def test_free_registration_rejects_duplicate_email(client):
    payload = {
        'full_name': 'Free Test Customer', 'email': 'duplicate@test.example',
        'password': 'CustomerStrongPassword!2026', 'device_id': 'e' * 48,
        'device_label': 'Android Test Device',
    }
    assert client.post('/api/auth/register', json=payload).status_code == 201
    second = dict(payload, device_id='d' * 48)
    assert client.post('/api/auth/register', json=second).status_code == 409


def test_performance_fee_is_thirty_percent_of_positive_net_only():
    net, fee = calculate_fee(100, -5, -5)
    assert net == 90
    assert fee == 27
    net_loss, fee_loss = calculate_fee(-100, 0, 0)
    assert net_loss == -100
    assert fee_loss == 0
