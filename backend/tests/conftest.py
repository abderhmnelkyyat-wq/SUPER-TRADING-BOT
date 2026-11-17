import os
from pathlib import Path

TEST_DB_DIR = Path(__file__).resolve().parent / '.test_data'
TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
os.environ['APP_ENV'] = 'test'
os.environ['DATABASE_URL'] = f"sqlite:///{TEST_DB_DIR / 'super-trading-bot-test.db'}"
os.environ['AUTH_SECRET'] = 'test-auth-secret-which-is-long-enough-for-hmac-and-jwt'
os.environ['LICENSE_PEPPER'] = 'test-license-pepper-which-is-long-enough-and-independent'
os.environ['PUBLIC_APP_URL'] = 'http://testserver'

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine, SessionLocal
from app.models import User
from app.security import uid, hash_password

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db=SessionLocal()
    db.add(User(id=uid(),full_name='Project Owner',email='owner@test.example',password_hash=hash_password('OwnerStrongPass!2026'),role='owner',status='active'))
    db.commit(); db.close()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def owner_token(client):
    r=client.post('/api/owner/login',json={'email':'owner@test.example','password':'OwnerStrongPass!2026','device_id':'a'*48})
    assert r.status_code==200,r.text
    return r.json()['access_token']
