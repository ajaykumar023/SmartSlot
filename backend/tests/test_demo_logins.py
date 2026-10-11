from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Business, Appointment, AccountBusinessRole, UserAccount
from app.account_security import verify_hash
from seed_demo_logins import seed_logins, eligible_customers
from datetime import datetime, timezone, timedelta


def test_customer_account_seed_eligibility_idempotence_and_protection():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now=datetime.now(timezone.utc)
    with Session(engine) as db:
        b1=Business(name='Salon',category='salon',is_demo=True,demo_key='showcase_salon_a')
        b2=Business(name='Clinic',category='clinic',is_demo=True,demo_key='showcase_clinic')
        real=Business(name='Real',category='salon',is_demo=False)
        db.add_all([b1,b2,real]); db.flush()
        for branch, email, name, ref in [(b1,'demo.asha@aetherx.example','Asha Khanna','TEST-1'),
                                        (b2,'demo.asha@aetherx.example','Asha Khanna','TEST-2'),
                                        (b1,'real.customer@gmail.com','Real Customer','TEST-3'),
                                        (real,'demo.unsafe@aetherx.example','Unsafe','TEST-4')]:
            # DB schema requires more appointment attrs in PostgreSQL; SQLite accepts all required fields here.
            db.add(Appointment(business_id=branch.id,customer_email=email, customer_name=name, reference=ref,
                               service_id=1,staff_id=1,starts_at=now,ends_at=now+timedelta(minutes=30),
                               status='confirmed',qr_token_hash=(ref + 'x'*64)[:64],duration_minutes=30,buffer_minutes=0))
        db.commit()
        assert list(eligible_customers(db)) == ['demo.asha@aetherx.example']
        result=seed_logins(db,'Welcome1234!')
        db.commit()
        assert result['accounts_created']==1 and result['grants_created']==2
        account=db.scalar(select(UserAccount)); assert verify_hash('Welcome1234!',account.password_salt,account.password_hash)
        assert len(list(db.scalars(select(AccountBusinessRole))))==2
        result2=seed_logins(db,'CompletelyNewPassword2026!')
        db.commit()
        assert result2['accounts_created']==0 and result2['existing_accounts_skipped']==1
        assert verify_hash('Welcome1234!',account.password_salt,account.password_hash)
        assert not verify_hash('CompletelyNewPassword2026!',account.password_salt,account.password_hash)
    engine.dispose()


def test_seeded_demo_customer_login_scoped_and_password_protected(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.database import get_db
    from app.main import app
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    S = sessionmaker(engine)
    with S.begin() as db:
        b1=Business(name='Demo A',category='salon',demo_key='showcase_salon_a',is_demo=True,active=True)
        b2=Business(name='Demo B',category='salon',demo_key='showcase_salon_b',is_demo=True,active=True)
        db.add_all([b1,b2]); db.flush()
        db.add(Appointment(business_id=b1.id,customer_email='demo.asha@aetherx.example',customer_name='Asha Khanna',reference='LOGIN-1',
            service_id=1,staff_id=1,starts_at=datetime.now(timezone.utc),ends_at=datetime.now(timezone.utc)+timedelta(minutes=30),
            status='confirmed',qr_token_hash='testhash1',duration_minutes=30,buffer_minutes=0))
        b1_id,b2_id=b1.id,b2.id
    with S.begin() as db: seed_logins(db,'Welcome1234!')
    def override_db():
        with S() as db: yield db
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(settings, 'app_secret', 'X'*48)
    monkeypatch.setattr(settings, 'allow_insecure_demo_login', False)
    monkeypatch.setattr(settings, 'allow_insecure_demo_admin', False)
    try:
        with TestClient(app) as c:
            payload={'email':'demo.asha@aetherx.example','password':'Welcome1234!','business_id':b1_id,'role':'customer'}
            ok=c.post('/api/auth/login',json=payload)
            assert ok.status_code==200,ok.text
            assert ok.json()['user']['name']=='Asha Khanna'
            assert c.get('/api/auth/me',headers={'Authorization':'Bearer '+ok.json()['access_token']}).status_code==200
            assert c.post('/api/auth/login',json={**payload,'password':'NotThePassword'}).status_code==401
            assert c.post('/api/auth/login',json={**payload,'role':'admin'}).status_code==403
            assert c.post('/api/auth/login',json={**payload,'business_id':b2_id}).status_code==403
            assert c.post('/api/auth/demo',json={'role':'customer','name':'Anyone','email':'anyone@example.com','business_id':b1_id}).status_code==403
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
