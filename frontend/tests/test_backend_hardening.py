"""Focused tests for production-default access controls and notification dispatch."""
from datetime import time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.account_security import make_hash, verify_hash
from app.accounts_api import router
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import AccountBusinessRole, Business, UserAccount, Notification, NotificationDelivery, Staff, Service, StaffService
from app.notification_outbox import deliver_pending, validated_endpoint


def test_password_round_trip_and_validation():
    salt, digest = make_hash('Correct-Horse-2026!')
    assert verify_hash('Correct-Horse-2026!', salt, digest)
    assert not verify_hash('Incorrect', salt, digest)
    assert not verify_hash('Correct-Horse-2026!', 'bad salt', digest)


def test_notification_webhook_requires_https_or_localhost():
    assert validated_endpoint('https://trusted.example/api/hook')
    assert validated_endpoint('http://localhost:8765/callback')
    assert not validated_endpoint('http://external.example/send')
    assert not validated_endpoint('file:///etc/passwd')
    assert not validated_endpoint('https://user:pass@trusted.example/path')


def test_secure_login_admin_scope_employee_self_and_revoke(monkeypatch):
    e = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    S = sessionmaker(e, expire_on_commit=False)
    salt, digest = make_hash('Correct-Horse-2026!')
    with S.begin() as db:
        b1, b2 = Business(name='A', category='salon', is_demo=True), Business(name='B', category='salon', is_demo=True)
        db.add_all([b1, b2]); db.flush()
        st = Staff(business_id=b1.id, name='Ada', title='Stylist', active=True)
        db.add(st); db.flush()
        a = UserAccount(name='Ada Manager', email='manager@example.com', password_salt=salt, password_hash=digest,
                        active=True, auth_version=1)
        db.add(a); db.flush()
        db.add_all([AccountBusinessRole(account_id=a.id, business_id=b1.id, role='admin'),
                    AccountBusinessRole(account_id=a.id, business_id=b1.id, role='employee', staff_id=st.id)])
        ids=(b1.id, b2.id, a.id)
    def db_override():
        with S() as db: yield db
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(settings, 'app_secret', 'X' * 44)
    monkeypatch.setattr(settings, 'allow_insecure_demo_login', False)
    monkeypatch.setattr(settings, 'allow_insecure_demo_admin', False)
    try:
        with TestClient(app) as client:
            r=client.post('/api/auth/demo', json={'role':'admin','name':'Fake','email':'admin@smartslot.demo','business_id':ids[0]})
            assert r.status_code == 403
            r=client.post('/api/auth/login', json={'email':'manager@example.com','password':'WrongPassword','business_id':ids[0],'role':'admin'})
            assert r.status_code == 401
            r=client.post('/api/auth/login', json={'email':'manager@example.com','password':'Correct-Horse-2026!','business_id':ids[1],'role':'admin'})
            assert r.status_code == 403
            r=client.post('/api/auth/login', json={'email':'manager@example.com','password':'Correct-Horse-2026!','business_id':ids[0],'role':'admin'})
            assert r.status_code == 200, r.text
            token=r.json()['access_token']; h={'Authorization':'Bearer '+token}
            assert client.get('/api/admin/dashboard', params={'business_id':ids[1]}, headers=h).status_code == 403
            assert client.get('/api/auth/me', headers=h).status_code == 200
            emp=client.post('/api/auth/login', json={'email':'manager@example.com','password':'Correct-Horse-2026!','business_id':ids[0],'role':'employee'})
            assert emp.status_code == 200
            eh={'Authorization':'Bearer '+emp.json()['access_token']}
            assert client.get('/api/admin/staff', params={'business_id':ids[0]}, headers=eh).status_code == 403
            assert client.put('/api/employee/my-presence', params={'business_id':ids[0]}, headers=eh, json={'status':'break'}).status_code == 200
            with S.begin() as db:
                a=db.get(UserAccount, ids[2]); a.auth_version += 1
            assert client.get('/api/auth/me', headers=h).status_code == 401
    finally:
        app.dependency_overrides.clear()
        e.dispose()


def test_webhook_outbox_attempt_and_idempotent_send(monkeypatch):
    e = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    S=sessionmaker(e)
    with S.begin() as db:
        b=Business(name='B', category='repair_center'); db.add(b); db.flush()
        db.add(Notification(business_id=b.id, customer_email='demo@example.com', message='Appointment moved', simulated=True))
    monkeypatch.setattr(settings, 'notification_webhook_url', 'https://webhook.example/receive')
    monkeypatch.setattr(settings, 'notification_webhook_secret', 'S' * 40)
    messages=[]
    with S.begin() as db:
        result=deliver_pending(db,sender=lambda url,payload,sig,key: messages.append((payload,sig,key)))
        assert result['accepted_by_webhook']==1
    with S.begin() as db:
        assert deliver_pending(db,sender=lambda *args: messages.append(args))['processed']==0
        ledger=db.scalar(select(NotificationDelivery))
        assert ledger.status=='accepted_by_webhook'
    assert len(messages)==1
    e.dispose()


def test_webhook_failure_is_retryable_without_marking_as_sent(monkeypatch):
    e=create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    S=sessionmaker(e)
    with S.begin() as db:
        b=Business(name='Repair', category='repair_center'); db.add(b); db.flush()
        db.add(Notification(business_id=b.id, customer_email='fiction@example.invalid', message='Test notification', simulated=True))
    monkeypatch.setattr(settings, 'notification_webhook_url', 'https://trusted.example/receive')
    monkeypatch.setattr(settings, 'notification_webhook_secret', 'y' * 40)
    def fail(*args):
        raise TimeoutError('Simulated network failure')
    with S.begin() as db:
        result=deliver_pending(db, sender=fail)
        assert result['failed_retry_scheduled'] == 1
    with S.begin() as db:
        assert deliver_pending(db, sender=fail)['processed'] == 0
        delivery=db.scalar(select(NotificationDelivery))
        note=db.scalar(select(Notification))
        assert delivery.status=='retry'
        assert delivery.attempts==1
        assert delivery.next_attempt_at is not None
        assert note.simulated is True  # webhook failure cannot claim actual delivery
    e.dispose()
