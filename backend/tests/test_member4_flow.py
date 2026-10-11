"""SQLite integration tests of the FastAPI contract; production runs on PostgreSQL.
These are deterministic but DO NOT replace PostgreSQL transaction/concurrency verification.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Appointment, Availability, Business, BusinessHours, Service, SlotOffer, Staff, StaffService, WaitlistEntry
from app.qr import create_pass, token_hash
from app.queue_engine import available_for_shift, utc


@pytest.fixture
def ctx():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionForTest = sessionmaker(engine, expire_on_commit=False)
    with SessionForTest.begin() as db:
        b = Business(name="Clinic", category="clinic", timezone="UTC", is_demo=True, active=True,
            check_in_minutes=30, queue_shift_minutes=15, queue_grace_minutes=10, cancellation_cutoff_hours=2)
        b2 = Business(name="Other", category="salon", timezone="UTC", is_demo=True, active=True)
        db.add_all([b, b2]); db.flush()
        s = Service(business_id=b.id, name="Consultation", duration_minutes=30, active=True, buffer_minutes=5)
        person = Staff(business_id=b.id, name="Dr A", title="Doctor", active=True)
        db.add_all([s, person]); db.flush()
        db.add(StaffService(staff_id=person.id, service_id=s.id))
        for day in range(7):
            db.add_all([BusinessHours(business_id=b.id, weekday=day, opens_at=time(8), closes_at=time(18)),
                Availability(business_id=b.id, staff_id=person.id, weekday=day, start_time=time(8), end_time=time(18))])
        ids = (b.id, b2.id, s.id, person.id)
    def override_db():
        with SessionForTest() as db: yield db
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            def login(role, email, business_id=ids[0]):
                r = client.post('/api/auth/demo', json={"role":role,"name":"Demo User", "email":email,"business_id":business_id})
                assert r.status_code == 200, r.text
                return {"Authorization":"Bearer "+r.json()["access_token"]}
            yield client, SessionForTest, ids, login
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def booking(session_factory, ids, start, name='Original', email='original@example.com', status='confirmed'):
    token, _ = create_pass()
    with session_factory.begin() as db:
        row = Appointment(business_id=ids[0], service_id=ids[2], staff_id=ids[3],
            customer_name=name, customer_email=email, reference=f'SS-{token[:6].upper()}',
            qr_token_hash=token_hash(token), starts_at=start, ends_at=start + timedelta(minutes=30),
            duration_minutes=30, buffer_minutes=5, status=status)
        db.add(row); db.flush()
        return row.reference, token, row.id


def future_day_at(hour=12, minute=0):
    today = datetime.now(timezone.utc).date() + timedelta(days=3)
    return datetime.combine(today, time(hour,minute),timezone.utc)


def test_scan_preview_valid_then_duplicate_and_business_isolation(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    ref, secret, _ = booking(SF, ids, start)
    good = client.get('/api/admin/check-in/validate', params={'business_id':ids[0], 'code':secret}, headers=admin)
    assert good.status_code == 200 and good.json()['valid'] is True
    forbidden = client.get('/api/admin/check-in/validate', params={'business_id':ids[1], 'code':secret}, headers=admin)
    assert forbidden.status_code == 404
    scanned = client.post('/api/admin/check-in', params={'business_id':ids[0], 'code':secret}, headers=admin)
    assert scanned.status_code == 200 and scanned.json()['status'] == 'checked_in'
    duplicate = client.post('/api/admin/check-in', params={'business_id':ids[0], 'code':ref}, headers=admin)
    assert duplicate.status_code == 409


def test_scan_too_early_and_expired(ctx):
    client, SF, ids, login = ctx
    admin = login('admin','admin@smartslot.demo')
    ref, secret, _ = booking(SF, ids, datetime.now(timezone.utc)+timedelta(hours=4))
    assert client.post('/api/admin/check-in',params={'business_id':ids[0],'code':secret},headers=admin).status_code == 409
    old_ref, old_secret, _ = booking(SF, ids, datetime.now(timezone.utc)-timedelta(hours=2))
    assert client.post('/api/admin/check-in',params={'business_id':ids[0],'code':old_secret},headers=admin).status_code == 409


def test_waitlist_right_recipient_hold_and_accept(ctx):
    client, SF, ids, login = ctx
    original = login('customer','original@example.com')
    waiting = login('customer','waiting@example.com')
    stranger = login('customer','stranger@example.com')
    start = future_day_at()
    ref, _, source_id = booking(SF, ids, start)
    request = {'business_id':ids[0]}
    body = {'service_id':ids[2], 'preferred_date':start.date().isoformat(),
        'name':'Waiting Person','email':'waiting@example.com'}
    joined = client.post('/api/waitlist',params=request,json=body,headers=waiting)
    assert joined.status_code == 201
    assert client.post('/api/waitlist',params=request,json=body,headers=waiting).status_code == 409
    cancelled = client.post(f'/api/appointments/{ref}/cancel',params=request,headers=original)
    assert cancelled.status_code == 200, cancelled.text
    offers = client.get('/api/offers', params=request, headers=waiting)
    assert offers.status_code == 200, offers.text
    assert len(offers.json()) == 1 and offers.json()[0]['kind'] == 'waitlist'
    offer_id = offers.json()[0]['id']
    assert client.get('/api/offers', params=request, headers=original).json() == []
    assert client.get('/api/offers', params=request, headers=stranger).json() == []
    assert client.post(f'/api/offers/{offer_id}/accept',params=request,headers=stranger).status_code == 404
    # Offered slot is temporarily reserved and cannot be booked twice by other customers.
    avail = client.get('/api/slots',params={'business_id':ids[0], 'service_id':ids[2],
        'date_from':start.date().isoformat(),'date_to':start.date().isoformat(),'staff_id':ids[3]})
    assert avail.status_code == 200
    assert start.isoformat() not in [datetime.fromisoformat(x['starts_at']).astimezone(timezone.utc).isoformat() for x in avail.json()]
    acceptance = client.post(f'/api/offers/{offer_id}/accept',params=request,headers=waiting)
    assert acceptance.status_code == 200, acceptance.text
    payload = acceptance.json()
    assert payload['customer_email'] == 'waiting@example.com' and 'qr_image' not in payload  # Future passes stay locked
    assert payload['reference'] != ref and payload['status'] == 'confirmed'
    assert client.post(f'/api/offers/{offer_id}/accept',params=request,headers=waiting).status_code == 409


def test_decline_reoffers_next_customer(ctx):
    client, SF, ids, login = ctx
    first = login('customer','first@example.com')
    second = login('customer','second@example.com')
    start = future_day_at()
    ref, _, source_id = booking(SF, ids, start, email='owner@example.com')
    with SF.begin() as db:
        db.add_all([WaitlistEntry(business_id=ids[0],service_id=ids[2],customer_name='First',customer_email='first@example.com',
            preferred_date=start.date().isoformat(),status='waiting', created_at=datetime.now(timezone.utc)-timedelta(minutes=5)),
            WaitlistEntry(business_id=ids[0],service_id=ids[2],customer_name='Second',customer_email='second@example.com',
            preferred_date=start.date().isoformat(),status='waiting', created_at=datetime.now(timezone.utc))])
    owner = login('customer','owner@example.com')
    assert client.post(f'/api/appointments/{ref}/cancel',params={'business_id':ids[0]},headers=owner).status_code == 200
    a = client.get('/api/offers',params={'business_id':ids[0]},headers=first).json()
    assert len(a) == 1
    assert client.post(f'/api/offers/{a[0]["id"]}/decline',params={'business_id':ids[0]},headers=first).status_code == 200
    b = client.get('/api/offers',params={'business_id':ids[0]},headers=second).json()
    assert len(b)==1 and b[0]['id'] != a[0]['id']
    assert client.get('/api/offers',params={'business_id':ids[0]},headers=first).json()==[]


def test_waitlist_expiry_reoffers_next_customer(ctx):
    client, SF, ids, login = ctx
    start = future_day_at()
    ref, _, source_id = booking(SF, ids, start, email='owner@example.com')
    with SF.begin() as db:
        db.add_all([WaitlistEntry(business_id=ids[0], service_id=ids[2],customer_email=e,
            customer_name=e,preferred_date=start.date().isoformat(),status='waiting',
            created_at=datetime.now(timezone.utc)+timedelta(seconds=i))
            for i,e in enumerate(['first@example.com','second@example.com'])])
    owner = login('customer','owner@example.com')
    first = login('customer','first@example.com')
    second = login('customer','second@example.com')
    assert client.post(f'/api/appointments/{ref}/cancel', params={'business_id':ids[0]},headers=owner).status_code == 200
    first_offer = client.get('/api/offers', params={'business_id':ids[0]},headers=first).json()[0]
    with SF.begin() as db:
        offer = db.get(SlotOffer, first_offer['id'])
        offer.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    assert client.get('/api/offers',params={'business_id':ids[0]},headers=first).json()==[]
    assert len(client.get('/api/offers',params={'business_id':ids[0]},headers=second).json())==1


def test_shift_rejects_outside_staff_hours_and_overlaps(ctx):
    client, SF, ids, login=ctx
    admin = login('admin','admin@smartslot.demo')
    start = future_day_at(8, 0)
    ref, _, app_id = booking(SF, ids, start)
    offer = client.post(f'/api/admin/queue-shift/{ref}',params={'business_id':ids[0]},headers=admin)
    assert offer.status_code==409 and 'working hours' in offer.json()['detail']
    late = future_day_at(12,0)
    other_ref, _, _ = booking(SF, ids, late, name='Other', email='other@example.com')
    # A conflicting booking at 11:30 makes shift of booking at 12:30 impossible.
    r,_,_ = booking(SF,ids,future_day_at(11,30), name='A', email='a@example.com')
    ref2,_,_ = booking(SF,ids,future_day_at(12,30),name='B',email='b@example.com')
    assert client.post(f'/api/admin/queue-shift/{ref2}',params={'business_id':ids[0],
        'advance_minutes':30},headers=admin).status_code==409


def test_valid_shift_accept_and_original_slot_preservation(ctx):
    client, SF, ids, login=ctx
    start=future_day_at(12,0)
    ref, _, app_id=booking(SF,ids,start)
    admin=login('admin','admin@smartslot.demo')
    owner=login('customer','original@example.com')
    offer=client.post(f'/api/admin/queue-shift/{ref}',params={'business_id':ids[0]},headers=admin)
    assert offer.status_code==200, offer.text
    with SF() as db:
        assert db.get(Appointment, app_id).starts_at.replace(tzinfo=timezone.utc)==start
    ack=client.post(f'/api/offers/{offer.json()["offer_id"]}/accept',params={'business_id':ids[0]},headers=owner)
    assert ack.status_code==200, ack.text
    assert ack.json()['starts_at'].endswith("+00:00"), "API must return an explicit UTC offset"
    assert datetime.fromisoformat(ack.json()['starts_at']).astimezone(timezone.utc) == start-timedelta(minutes=15)


def test_arrival_self_report_and_staff_presence_do_not_auto_cancel(ctx):
    client, SF, ids, login=ctx
    ref,_,app_id=booking(SF,ids,future_day_at(),name='Customer',email='a@example.com')
    customer=login('customer','a@example.com')
    admin=login('admin','admin@smartslot.demo')
    params={'business_id':ids[0]}
    assert client.post(f'/api/appointments/{ref}/arrival',params=params,headers=customer,
        json={'status':'on_the_way','eta_minutes':35}).status_code==200
    queue=client.get('/api/queue/mine',params=params,headers=customer)
    assert queue.status_code==200 and queue.json()[0]['eta_minutes']==35
    set_presence=client.post(f'/api/admin/staff/{ids[3]}/presence',params=params,
        headers=admin,json={'status':'break'})
    assert set_presence.status_code==200
    evaluated=client.post('/api/admin/queue-shift/evaluate',params=params,headers=admin)
    assert evaluated.status_code==200 and ids[3] in evaluated.json()['staff_unavailable_ids']
    with SF() as db:
        assert db.get(Appointment,app_id).status=='confirmed'


def test_qr_reissue_revokes_previous_token_and_requires_owner(ctx):
    client, SF, ids, login=ctx
    start=datetime.now(timezone.utc)+timedelta(minutes=10)
    ref, secret, _=booking(SF,ids,start)
    owner=login('customer','original@example.com')
    other=login('customer','stranger@example.com')
    admin=login('admin','admin@smartslot.demo')
    path=f'/api/appointments/{ref}/qr/reissue'
    params={'business_id':ids[0]}
    assert client.post(path,params=params,headers=other).status_code==404
    renewed=client.post(path,params=params,headers=owner)
    assert renewed.status_code==200 and renewed.json()['qr_token']!=secret
    assert client.post('/api/admin/check-in',params={**params,'code':secret},headers=admin).status_code==404
    assert client.post('/api/admin/check-in',params={**params,'code':renewed.json()['qr_token']},headers=admin).status_code==200
    assert client.post(path,params=params,headers=owner).status_code==409


def test_waitlist_withdrawal_only_own_entry(ctx):
    client, SF, ids, login=ctx
    date=future_day_at().date()
    owner=login('customer','user1@example.com')
    stranger=login('customer','user2@example.com')
    params={'business_id':ids[0]}
    entry=client.post('/api/waitlist',params=params,headers=owner,json={
        'service_id':ids[2], 'preferred_date':date.isoformat(),
        'name':'Owner', 'email':'user1@example.com'}).json()
    assert client.post(f'/api/waitlist/{entry["id"]}/withdraw',params=params,headers=stranger).status_code==404
    assert client.post(f'/api/waitlist/{entry["id"]}/withdraw',params=params,headers=owner).status_code==200
    assert client.post(f'/api/waitlist/{entry["id"]}/withdraw',params=params,headers=owner).status_code==409
    assert client.get('/api/waitlist/mine',params=params,headers=owner).json()[0]['status']=='withdrawn'


def test_admin_queue_overview_protected_and_tenant_scoped(ctx):
    client,SF,ids,login=ctx
    now=datetime.now(timezone.utc)
    ref, _, _=booking(SF,ids,future_day_at())
    customer=login('customer','original@example.com')
    admin=login('admin','admin@smartslot.demo')
    assert client.get('/api/admin/queue/overview',params={'business_id':ids[0]},headers=customer).status_code==403
    date=future_day_at().date().isoformat()
    result=client.get('/api/admin/queue/overview',params={'business_id':ids[0],'date_on':date},headers=admin)
    assert result.status_code==200
    queue=result.json()['staff_queues']
    assert any(a['reference']==ref for item in queue for a in item['appointments'])
    elsewhere=client.get('/api/admin/queue/overview',params={'business_id':ids[1],'date_on':date},headers=admin)
    assert elsewhere.status_code==200
    assert all(a['reference']!=ref for item in elsewhere.json()['staff_queues'] for a in item['appointments'])


def test_qr_secure_post_body_scanner(ctx):
    client,SF,ids,login=ctx
    ref,token,_=booking(SF,ids,datetime.now(timezone.utc)+timedelta(minutes=5))
    admin=login('admin','admin@smartslot.demo')
    params={'business_id':ids[0]}
    preview=client.post('/api/admin/check-in/preview',params=params,headers=admin,json={'code':token})
    assert preview.status_code==200 and preview.json()['valid']
    checked=client.post('/api/admin/check-in/confirm',params=params,headers=admin,json={'code':token})
    assert checked.status_code==200 and checked.json()['status']=='checked_in'
    assert client.post('/api/admin/check-in/confirm',params=params,headers=admin,json={'code':token}).status_code==409

# GeoSmart limited delay and read-only admin customer simulation

def test_simulated_customer_flows_require_admin_and_do_not_mutate_database(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    customer = login('customer', 'rahul@example.com')
    before = 0
    with SF() as db:
        before = len(db.scalars(select(Appointment)).all())
    body = {'scenario': 'gap', 'traffic_delay_minutes': 25,
            'max_delay_minutes': 30, 'action': 'accept'}
    denied = client.post('/api/admin/simulation/limited-delay', params={'business_id': ids[0]},
                         headers=customer, json=body)
    assert denied.status_code == 403
    response = client.post('/api/admin/simulation/limited-delay', params={'business_id': ids[0]},
                           headers=admin, json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['simulation_only'] is True
    assert data['outcome'] == 'accepted'
    assert data['selected']['delay_minutes'] == 30
    assert data['confirmed_customers_displaced'] == 0
    people = {p['customer']: p for p in data['customers']}
    assert people['Rahul']['time'] == '10:30'
    assert people['Priya']['time'] == '11:15'
    assert people['Arjun']['time'] == '11:50'
    assert people['Meera']['status'] == 'offer_pending'
    with SF() as db:
        assert len(db.scalars(select(Appointment)).all()) == before


def test_simulation_says_no_if_fully_booked_and_keeps_original(ctx):
    client, SF, ids, login = ctx
    admin = login('admin','admin@smartslot.demo')
    data = client.post('/api/admin/simulation/limited-delay', params={'business_id':ids[0]},
                       headers=admin, json={'scenario':'fully_booked','traffic_delay_minutes':25,
                                            'max_delay_minutes':30,'action':'accept'}).json()
    assert data['outcome'] == 'manual_review'
    assert data['options'] == []
    assert data['waitlist_offer_created_in_demo'] is False
    assert next(p for p in data['customers'] if p['customer'] == 'Rahul')['time'] == '10:00'
    assert data['confirmed_customers_displaced'] == 0


def test_simulation_keeps_on_time_customer_without_delay(ctx):
    client, SF, ids, login = ctx
    admin = login('admin','admin@smartslot.demo')
    data = client.post('/api/admin/simulation/limited-delay',params={'business_id':ids[0]},
                      headers=admin,json={'scenario':'near_on_time','traffic_delay_minutes':3,
                                          'max_delay_minutes':30,'action':'preview'}).json()
    assert data['outcome'] == 'on_time'
    assert data['selected'] is None


def test_real_delay_algorithm_caps_at_30_minutes_and_preserves_confirmed_neighbors(ctx):
    from app.queue_engine import delay_recommendations
    client, SF, ids, login = ctx
    start = future_day_at(12, 0)
    ref, _, original_id = booking(SF, ids, start)
    now = start - timedelta(minutes=25)
    with SF() as db:
        business = db.get(Business, ids[0])
        row = db.get(Appointment, original_id)
        options = delay_recommendations(db, business, row, eta_minutes=40, max_delay_minutes=30, now=now)
        assert [v['delay_minutes'] for v in options] == [30]
        assert delay_recommendations(db,business,row,eta_minutes=40,max_delay_minutes=15,now=now) == []
        assert delay_recommendations(db,business,row,eta_minutes=10,max_delay_minutes=30,now=now) == []
    # A confirmed neighbor makes the 12:30-13:00 postponement unavailable.
    booking(SF, ids, start + timedelta(minutes=30), name='Priya', email='priya@example.com')
    with SF() as db:
        assert delay_recommendations(db,db.get(Business, ids[0]),db.get(Appointment,original_id),
                                     eta_minutes=40,max_delay_minutes=30,now=now) == []


def test_customer_can_request_and_accept_short_delay_without_moving_neighbor(ctx, monkeypatch):
    """End-to-end: preview -> offer -> customer accepts; unrelated booking unchanged."""
    import app.main as main_module
    import app.queue_engine as queue_engine_module
    client, SF, ids, login = ctx
    original_start = future_day_at(10, 0)
    simulated_now = original_start - timedelta(minutes=25)
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return simulated_now if tz is None else simulated_now.astimezone(tz)
    monkeypatch.setattr(main_module, 'datetime', FrozenDatetime)
    monkeypatch.setattr(queue_engine_module, 'datetime', FrozenDatetime)

    ref, _, appointment_id = booking(SF,ids,original_start)
    neighbor_ref, _, neighbor_id = booking(SF,ids,original_start + timedelta(minutes=75),
                                           name='Priya',email='priya@example.com')
    owner = login('customer','original@example.com')
    other = login('customer','priya@example.com')
    body = {'eta_minutes':40,'max_delay_minutes':30}
    preview = client.post(f'/api/appointments/{ref}/delay-options',params={'business_id':ids[0]},
                          json=body,headers=owner)
    assert preview.status_code == 200, preview.text
    assert [s['delay_minutes'] for s in preview.json()['options']] == [30]
    blocked = client.post(f'/api/appointments/{ref}/delay-request',params={'business_id':ids[0]},
                          json=body,headers=other)
    assert blocked.status_code == 404
    make = client.post(f'/api/appointments/{ref}/delay-request',params={'business_id':ids[0]},
                       json=body,headers=owner)
    assert make.status_code == 200,make.text
    offer_id = make.json()['offer_id']
    with SF() as db:
        assert utc(db.get(Appointment,appointment_id).starts_at) == original_start
    duplicate = client.post(f'/api/appointments/{ref}/delay-request',params={'business_id':ids[0]},
                            json=body,headers=owner)
    assert duplicate.status_code == 409
    wrong_owner = client.post(f'/api/offers/{offer_id}/accept',params={'business_id':ids[0]},headers=other)
    assert wrong_owner.status_code == 404
    accepted = client.post(f'/api/offers/{offer_id}/accept',params={'business_id':ids[0]},headers=owner)
    assert accepted.status_code == 200, accepted.text
    assert datetime.fromisoformat(accepted.json()['starts_at']).astimezone(timezone.utc) == original_start+timedelta(minutes=30)
    with SF() as db:
        assert utc(db.get(Appointment,neighbor_id).starts_at) == original_start+timedelta(minutes=75)
        assert db.get(Appointment,appointment_id).status == 'confirmed'

# GeoSmart auto-reroute read-only demo: pre-authorized, no per-transfer acceptance

def test_geo_reroute_auto_selects_nearest_reachable_qualified_branch(ctx):
    client, SF, ids, login = ctx
    admin = login('admin','admin@smartslot.demo')
    before = len(list(SF().scalars(select(Appointment)).all()))
    r = client.post('/api/admin/simulation/geo-reroute', params={'business_id': ids[0]},
        headers=admin, json={'scenario':'gap','traffic_delay_minutes':25,
            'max_delay_minutes':30,'auto_reroute_opt_in':True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['simulation_only'] and data['outcome'] == 'auto_rerouted'
    assert data['selected']['branch'] == 'Northstar East'
    assert data['selected']['time'] == '10:00'
    assert data['confirmed_customers_displaced'] == 0
    assert data['waitlist_offer_created_in_demo']
    assert next(x for x in data['customers'] if x['customer'] == 'Rahul')['branch'] == 'Northstar East'
    assert len(list(SF().scalars(select(Appointment)).all())) == before


def test_geo_reroute_uses_alternate_when_nearest_busy_or_unqualified(ctx):
    client, SF, ids, login = ctx
    admin = login('admin','admin@smartslot.demo')
    for scenario in ('nearest_full','nearest_unqualified'):
        r = client.post('/api/admin/simulation/geo-reroute',params={'business_id': ids[0]},
            headers=admin,json={'scenario':scenario,'traffic_delay_minutes':25,
                'max_delay_minutes':30,'auto_reroute_opt_in':True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data['selected']['branch'] == 'Northstar South'
        assert data['selected']['time'] == '10:15'
        assert data['confirmed_customers_displaced'] == 0


def test_geo_reroute_requires_prior_opt_in_and_never_auto_cancels(ctx):
    client, SF, ids, login = ctx
    admin = login('admin','admin@smartslot.demo')
    customer = login('customer','rahul@example.com')
    params={'business_id':ids[0]}
    payload={'scenario':'gap','traffic_delay_minutes':25,'max_delay_minutes':30}
    denied = client.post('/api/admin/simulation/geo-reroute',params=params,headers=customer,json=payload)
    assert denied.status_code == 403
    r = client.post('/api/admin/simulation/geo-reroute',params=params,headers=admin,json=payload)
    assert r.status_code == 200
    assert r.json()['outcome'] == 'opt_in_required'
    assert r.json()['selected'] is None
    r = client.post('/api/admin/simulation/geo-reroute',params=params,headers=admin,
        json={**payload,'scenario':'fully_booked','auto_reroute_opt_in':True})
    assert r.json()['outcome'] == 'manual_review'
    assert r.json()['selected'] is None
    assert next(x for x in r.json()['customers'] if x['customer']=='Rahul')['time'] == '10:00'
    r = client.post('/api/admin/simulation/geo-reroute',params=params,headers=admin,
        json={**payload,'scenario':'near_on_time','traffic_delay_minutes':3,'auto_reroute_opt_in':True})
    assert r.json()['outcome'] == 'on_time'


def test_admin_toggle_services_disables_booking_and_can_restore(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    response = client.patch(f'/api/admin/services/{ids[2]}',
        params={'business_id': ids[0]}, json={'active': False}, headers=admin)
    assert response.status_code == 200 and response.json()['active'] is False
    rows = client.get('/api/services', params={'business_id':ids[0]}).json()
    assert all(row['id'] != ids[2] for row in rows)
    restore = client.patch(f'/api/admin/services/{ids[2]}',
        params={'business_id': ids[0]}, json={'active': True}, headers=admin)
    assert restore.status_code == 200 and restore.json()['active'] is True


def test_auto_book_assigns_qualified_staff_and_notifies_customer(ctx):
    client, SF, ids, login = ctx
    owner = login('customer','autobook@example.com')
    target = (datetime.now(timezone.utc)+timedelta(days=3)).date()
    response = client.post('/api/appointments/auto-book',params={'business_id':ids[0]}, headers=owner,
        json={'service_id':ids[2], 'preferred_date':target.isoformat(),
              'name':'Auto Customer','email':'autobook@example.com'})
    assert response.status_code==201, response.text
    data=response.json()
    assert data['allocation']['mode']=='automatic'
    assert data['staff_id']==ids[3] and 'qr_image' not in data  # Future passes stay locked
    assert data['status']=='confirmed'
    notices=client.get('/api/notifications',params={'business_id':ids[0]},headers=owner)
    assert notices.status_code==200 and any('confirmed' in n['message'] for n in notices.json())


def test_location_requires_configuration_and_traffic_failure_never_cancels(ctx,monkeypatch):
    client, SF, ids, login = ctx
    owner=login('customer','original@example.com')
    admin=login('admin','admin@smartslot.demo')
    start=datetime.now(timezone.utc)+timedelta(minutes=60)
    ref, _, aid = booking(SF,ids,start)
    location={'latitude':12.97,'longitude':77.59,'accuracy_meters':20,
              'captured_at':datetime.now(timezone.utc).isoformat()}
    no_location=client.post(f'/api/appointments/{ref}/travel-eta',params={'business_id':ids[0]},headers=owner,json=location)
    assert no_location.status_code==409
    saved=client.put('/api/admin/location',params={'business_id':ids[0]},headers=admin,
                     json={'latitude':12.98,'longitude':77.60})
    assert saved.status_code==200
    from app.georoutes import RoutingUnavailable
    def fails(*args,**kw):raise RoutingUnavailable('API not available')
    monkeypatch.setattr('app.geosmart_api.estimate_travel',fails)
    failed=client.post(f'/api/appointments/{ref}/travel-eta',params={'business_id':ids[0]},headers=owner,json=location)
    assert failed.status_code==503
    with SF() as db:
        assert db.get(Appointment,aid).status=='confirmed'


def test_real_traffic_late_alert_once_and_private_gps(ctx,monkeypatch):
    client,SF,ids,login=ctx
    owner=login('customer','original@example.com')
    admin=login('admin','admin@smartslot.demo')
    ref, _, aid=booking(SF,ids,datetime.now(timezone.utc)+timedelta(minutes=30))
    client.put('/api/admin/location',params={'business_id':ids[0]},headers=admin,
               json={'latitude':12.98,'longitude':77.60})
    monkeypatch.setattr('app.geosmart_api.estimate_travel',lambda *a,**kw:
        {'eta_minutes':45,'distance_km':11.0,'source':'tomtom_live_traffic',
         'traffic_aware':True,'automatic_rescheduling_allowed':True})
    body={'latitude':12.97,'longitude':77.59,'accuracy_meters':19,
          'captured_at':datetime.now(timezone.utc).isoformat()}
    for _ in range(2):
        result=client.post(f'/api/appointments/{ref}/travel-eta',params={'business_id':ids[0]},
                           headers=owner,json=body)
        assert result.status_code==200, result.text
        assert result.json()['status']=='likely_late'
        assert result.json()['automatic_rescheduling_allowed'] is False
        assert 'latitude' not in result.json()
    alerts=client.get('/api/admin/alerts',params={'business_id':ids[0]},headers=admin).json()
    assert len([x for x in alerts if x['kind']=='late_arrival'])==1
    with SF() as db:
        assert db.get(Appointment,aid).status=='confirmed'


def test_allocator_offers_released_slot_once_and_alerts_admin(ctx):
    client,SF,ids,login=ctx
    admin=login('admin','admin@smartslot.demo')
    waiting=login('customer','newwaiter@example.com')
    start=future_day_at(12,0)
    ref,_,aid=booking(SF,ids,start,status='cancelled')
    joined=client.post('/api/waitlist',params={'business_id':ids[0]},headers=waiting,
      json={'service_id':ids[2],'preferred_date':start.date().isoformat(),
            'name':'New Waiter','email':'newwaiter@example.com'})
    assert joined.status_code==201, joined.text
    first=client.post('/api/admin/automation/run',params={'business_id':ids[0]},headers=admin)
    assert first.status_code==200 and first.json()['created_offers']==1,first.text
    second=client.post('/api/admin/automation/run',params={'business_id':ids[0]},headers=admin)
    assert second.status_code==200 and second.json()['created_offers']==0,second.text
    offers=client.get('/api/offers',params={'business_id':ids[0]},headers=waiting)
    assert len(offers.json())==1
    alerts=client.get('/api/admin/alerts',params={'business_id':ids[0]},headers=admin)
    assert any(a['reference']==ref and a['kind']=='waitlist_offer' for a in alerts.json())


def test_qr_future_day_locked_even_if_requested_directly(ctx):
    client, SF, ids, login = ctx
    start = future_day_at(12, 0)
    ref, _, _ = booking(SF, ids, start)
    owner = login('customer', 'original@example.com')
    stranger = login('customer', 'other@example.com')
    params = {'business_id': ids[0]}
    prefix = f'/api/appointments/{ref}/qr'
    status = client.get(prefix + '/status', params=params, headers=owner)
    assert status.status_code == 200, status.text
    assert status.json()['available'] is False and status.json()['reason'] == 'scheduled'
    assert client.post(prefix + '/activate', params=params, headers=owner).status_code == 409
    assert client.post(prefix + '/reissue', params=params, headers=owner).status_code == 409
    assert client.get(prefix + '/status', params=params, headers=stranger).status_code == 404
    assert client.post(prefix + '/activate', params=params, headers=stranger).status_code == 404


def test_qr_day_activation_creates_scannable_token_and_revokes_previous(ctx):
    client, SF, ids, login = ctx
    start = datetime.now(timezone.utc) + timedelta(minutes=12)
    ref, secret, _ = booking(SF, ids, start)
    owner = login('customer', 'original@example.com')
    admin = login('admin', 'admin@smartslot.demo')
    params = {'business_id': ids[0]}
    prefix = f'/api/appointments/{ref}/qr'
    status = client.get(prefix + '/status', params=params, headers=owner)
    assert status.status_code == 200 and status.json()['available'] is True
    pass_result = client.post(prefix + '/activate', params=params, headers=owner)
    assert pass_result.status_code == 200, pass_result.text
    assert pass_result.json()['qr_image'].startswith('data:image/png;base64,')
    new_token = pass_result.json()['qr_token']
    assert new_token != secret
    assert client.post('/api/admin/check-in',params={**params,'code':secret},headers=admin).status_code == 404
    assert client.post('/api/admin/check-in',params={**params,'code':new_token},headers=admin).status_code == 200


def test_live_gps_provider_status_does_not_expose_server_key(ctx, monkeypatch):
    from app.config import settings
    client, SF, ids, login = ctx
    customer = login('customer', 'original@example.com')
    monkeypatch.setattr(settings, 'tomtom_routing_api_key', 'private-server-secret')
    response = client.get('/api/travel/provider-status', params={'business_id': ids[0]}, headers=customer)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result == {'provider': 'tomtom', 'routes_configured': True,
                      'traffic_aware': True, 'demo_mode': False}
    assert 'private-server-secret' not in response.text


def test_staff_break_blocks_new_slots_and_recovers_on_delete(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    day = future_day_at(10, 0)
    business_id, _, service_id, staff_id = ids
    query = {'business_id': business_id, 'service_id': service_id,
             'date_from': day.date().isoformat(), 'date_to': day.date().isoformat(), 'staff_id': staff_id}
    def hours():
        resp = client.get('/api/slots', params=query)
        assert resp.status_code == 200, resp.text
        return [datetime.fromisoformat(slot['starts_at']).astimezone(timezone.utc) for slot in resp.json()]
    assert day in hours()
    body = {'starts_at': (day + timedelta(minutes=20)).isoformat(),
            'ends_at': (day + timedelta(minutes=50)).isoformat(), 'reason': 'break'}
    created = client.post(f'/api/admin/staff/{staff_id}/absences',
                          params={'business_id': business_id}, json=body, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json()['automatic_cancellation'] is False
    assert day not in hours()
    assert day + timedelta(hours=1) in hours()
    repeated = client.post(f'/api/admin/staff/{staff_id}/absences',
                           params={'business_id': business_id}, json=body, headers=admin)
    assert repeated.status_code == 409
    listed = client.get(f'/api/admin/staff/{staff_id}/absences',
                        params={'business_id': business_id}, headers=admin)
    assert listed.status_code == 200 and len(listed.json()) == 1
    deleted = client.delete(f'/api/admin/staff/{staff_id}/absences/{created.json()["id"]}',
                            params={'business_id': business_id}, headers=admin)
    assert deleted.status_code == 200
    assert day in hours()


def test_staff_break_alerts_on_existing_booking_without_cancelling_it(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    start = future_day_at(10, 0)
    ref, _, app_id = booking(SF, ids, start)
    created = client.post(f'/api/admin/staff/{ids[3]}/absences',
        params={'business_id': ids[0]}, headers=admin,
        json={'starts_at': (start + timedelta(minutes=5)).isoformat(),
              'ends_at': (start + timedelta(minutes=20)).isoformat(), 'reason': 'leave'})
    assert created.status_code == 201, created.text
    assert created.json()['affected_appointment_references'] == [ref]
    with SF() as db:
        from app.models import AdminAlert
        assert db.get(Appointment, app_id).status == 'confirmed'
        alert = db.scalar(select(AdminAlert).where(AdminAlert.business_id == ids[0],
                                                   AdminAlert.reference == ref,
                                                   AdminAlert.kind == 'staff_absence'))
        assert alert is not None
    customer = login('customer', 'customer@example.com')
    forbidden = client.post(f'/api/admin/staff/{ids[3]}/absences',
        params={'business_id': ids[0]}, headers=customer,
        json={'starts_at': start.isoformat(), 'ends_at': (start + timedelta(minutes=30)).isoformat()})
    assert forbidden.status_code in (401, 403)


def test_organizations_only_connect_explicit_compatible_branches(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    businesses = client.get('/api/admin/branches', params={'business_id': ids[0]}, headers=admin)
    assert businesses.status_code == 200 and len(businesses.json()['branches']) == 1
    created = client.post('/api/admin/organizations',
        params={'business_id': ids[0]}, headers=admin,
        json={'name': 'Northstar Family Clinics', 'slug': 'northstar-family-clinics'})
    assert created.status_code == 201, created.text
    org_id = created.json()['id']
    # The other initial fixture business is a salon, not an equivalent clinic.
    incompatible = client.post(f'/api/admin/organizations/{org_id}/attach',
        params={'business_id': ids[0]}, headers=admin, json={'target_business_id': ids[1]})
    assert incompatible.status_code == 409
    with SF.begin() as db:
        from app.models import Business
        clone = Business(name='Second Clinic Branch', category='clinic', timezone='UTC',
                         active=True, is_demo=True)
        db.add(clone); db.flush(); clone_id = clone.id
    # Demo tokens snapshot accessible businesses at login. Re-login after provisioning.
    admin = login('admin', 'admin@smartslot.demo')
    attached = client.post(f'/api/admin/organizations/{org_id}/attach',
        params={'business_id': ids[0]}, headers=admin, json={'target_business_id': clone_id})
    assert attached.status_code == 200, attached.text
    related = client.get('/api/admin/branches', params={'business_id': ids[0]}, headers=admin)
    assert {b['id'] for b in related.json()['branches']} == {ids[0], clone_id}


def test_auto_book_assigns_another_qualified_staff_when_first_on_leave(ctx):
    client, SF, ids, login = ctx
    admin = login('admin', 'admin@smartslot.demo')
    customer = login('customer', 'autoabsence@example.com')
    today = future_day_at(10, 0)
    with SF.begin() as db:
        second = Staff(business_id=ids[0], name='Backup Doctor', title='Doctor', active=True)
        db.add(second); db.flush(); backup_id = second.id
        db.add(StaffService(staff_id=backup_id, service_id=ids[2]))
        for n in range(7):
            db.add(Availability(business_id=ids[0], staff_id=backup_id,
                                weekday=n, start_time=time(8), end_time=time(18)))
    unavailable = client.post(f'/api/admin/staff/{ids[3]}/absences',
        params={'business_id': ids[0]}, headers=admin,
        json={'starts_at': today.replace(hour=8).isoformat(),
              'ends_at': today.replace(hour=18).isoformat(), 'reason': 'leave'})
    assert unavailable.status_code == 201, unavailable.text
    assigned = client.post('/api/appointments/auto-book', params={'business_id': ids[0]},
        headers=customer, json={'service_id': ids[2], 'preferred_date': today.date().isoformat(),
                                'name': 'Absence Test Customer', 'email': 'autoabsence@example.com'})
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()['staff_id'] == backup_id
    assert assigned.json()['allocation']['mode'] == 'automatic'
