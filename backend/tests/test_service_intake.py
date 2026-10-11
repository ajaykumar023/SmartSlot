"""All supported categories, booking paths, privacy and recovery handoffs.
SQLite tests do not replace real PostgreSQL security/concurrency checks.
"""
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import importlib.util
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.database import Base, get_db
from app.main import app
from app.models import (Business, Service, Staff, StaffService, BusinessHours,
    Availability, Appointment, BookingHaircutPreference, BookingServiceIntake, RecoveryEvent)
from app.auth import issue_token
from tests.test_recovery import setup, make_booking


EXAMPLES = {
    "salon": {"desired_style": "Low taper fade", "preferred_length": "medium"},
    "clinic": {"visit_reason": "Routine general consultation", "visit_type": "First visit"},
    "repair_center": {"item_type": "Laptop", "reported_issue": "Screen flickers"},
    "consultant": {"consultation_goal": "Plan an app launch", "project_context": "Early prototype"},
}


@pytest.fixture
def multibusiness():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SF = sessionmaker(engine, expire_on_commit=False)
    with SF.begin() as db:
        ids = {}
        for kind in EXAMPLES:
            b = Business(name=f"Test {kind}", category=kind, timezone="UTC", is_demo=True, active=True)
            db.add(b); db.flush()
            service = Service(business_id=b.id, name=f"{kind} service", duration_minutes=30,
                              buffer_minutes=0, active=True)
            staff = Staff(business_id=b.id, name="Alex", active=True)
            db.add_all([service, staff]); db.flush()
            db.add(StaffService(staff_id=staff.id, service_id=service.id))
            for day in range(7):
                db.add(BusinessHours(business_id=b.id, weekday=day, opens_at=time(8), closes_at=time(18)))
                db.add(Availability(business_id=b.id, staff_id=staff.id, weekday=day,
                                    start_time=time(8), end_time=time(18)))
            ids[kind] = (b.id, service.id, staff.id)
    def override():
        with SF() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            def token(kind, role="customer", email="owner@example.com"):
                business_id=ids[kind][0]
                return {"Authorization": "Bearer " + issue_token(role,"Demo",email,business_id,[business_id])}
            yield client, SF, ids, token
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def booking_request(kind, ids):
    business_id, service_id, _ = ids[kind]
    day = datetime.now(timezone.utc).date() + timedelta(days=4)
    starts = datetime.combine(day,time(10),timezone.utc)
    return {"service_id":service_id, "starts_at":starts.isoformat(),
            "name":"Owner", "email":"owner@example.com",
            "service_intake":{"summary":f"Need {kind} appointment",
                              "notes":"Please discuss before starting",
                              "answers":EXAMPLES[kind]}}


@pytest.mark.parametrize("kind", list(EXAMPLES))
def test_all_industries_booking_and_professional_briefing(multibusiness, kind):
    client, SF, ids, token = multibusiness
    b, service, _ = ids[kind]
    template=client.get(f"/api/businesses/{b}/intake-template",params={"service_id":service})
    assert template.status_code == 200, template.text
    assert template.json()["category"] == kind
    assert set(EXAMPLES[kind]).issubset({f["key"] for f in template.json()["fields"]})
    payload=booking_request(kind, ids)
    booking=client.post("/api/appointments",params={"business_id":b},headers=token(kind),json=payload)
    assert booking.status_code == 201, booking.text
    ref=booking.json()["reference"]
    get=client.get(f"/api/appointments/{ref}/service-intake",params={"business_id":b},headers=token(kind))
    assert get.status_code == 200 and get.json()["intake"] == payload["service_intake"]
    briefing=client.get(f"/api/admin/appointments/{ref}/service-briefing",
                        params={"business_id":b},headers=token(kind,"admin","admin@example.com"))
    assert briefing.status_code == 200, briefing.text
    assert briefing.json()["intake"] == payload["service_intake"]
    assert briefing.json()["business_category"] == kind
    assert "customer_email" not in briefing.json()
    assert client.get(f"/api/appointments/{ref}/service-intake",params={"business_id":b},
                      headers=token(kind,"customer","stranger@example.com")).status_code == 404
    with SF() as db:
        saved=db.scalars(select(BookingServiceIntake)).all()
        assert len(saved)==1 and saved[0].category==kind


def test_invalid_category_fields_and_validation(multibusiness):
    client,SF,ids,token=multibusiness
    clinic_id,service_id,_=ids["clinic"]
    body=booking_request("clinic",ids)
    body["service_intake"]["answers"]={"desired_style":"taper"}
    assert client.post("/api/appointments",params={"business_id":clinic_id},
                       headers=token("clinic"),json=body).status_code==422
    body["service_intake"]={"notes":"a"*1201}
    assert client.post("/api/appointments",params={"business_id":clinic_id},
                       headers=token("clinic"),json=body).status_code==422
    body["service_intake"]={"answers":{"visit_reason":"x"*301}}
    assert client.post("/api/appointments",params={"business_id":clinic_id},
                       headers=token("clinic"),json=body).status_code==422
    body["service_intake"]={"reference_image_path":"/private/photo.png"}
    assert client.post("/api/appointments",params={"business_id":clinic_id},
                       headers=token("clinic"),json=body).status_code==422
    body["service_intake"]={"summary":"General visit"}
    body["haircut_preferences"]={"style":"fade"}
    assert client.post("/api/appointments",params={"business_id":clinic_id},
                       headers=token("clinic"),json=body).status_code==422
    with SF() as db:
        assert db.scalars(select(BookingServiceIntake)).all()==[]
        assert db.scalars(select(Appointment)).all()==[]


def test_auto_booking_all_categories_persists_intake(multibusiness):
    client,SF,ids,token=multibusiness
    day=(datetime.now(timezone.utc)+timedelta(days=5)).date().isoformat()
    for kind,(b,service,_) in ids.items():
        body={"service_id":service,"preferred_date":day,"name":"Owner","email":"owner@example.com",
              "service_intake":{"summary": "Please prepare", "answers":EXAMPLES[kind]}}
        created=client.post('/api/appointments/auto-book',params={'business_id':b},
                            headers=token(kind),json=body)
        assert created.status_code==201,(kind,created.text)
        result=client.get(f'/api/appointments/{created.json()["reference"]}/service-intake',
                          params={'business_id':b},headers=token(kind))
        assert result.status_code==200 and result.json()['intake']==body['service_intake']|{"notes":""}


def test_edit_requires_owner_and_not_started(multibusiness):
    client,SF,ids,token=multibusiness
    kind='repair_center'; b, _, _=ids[kind]
    created=client.post('/api/appointments',params={'business_id':b},headers=token(kind),
                        json=booking_request(kind,ids))
    assert created.status_code==201,created.text
    ref=created.json()['reference']
    url=f'/api/appointments/{ref}/service-intake'
    edited=client.put(url,params={'business_id':b},headers=token(kind),
                      json={'summary':'Revised request','answers':{'model':'Laptop 2020'}})
    assert edited.status_code==200 and edited.json()['intake']['answers']=={'model':'Laptop 2020'}
    assert edited.json()['intake']['notes']==''
    assert client.put(url,params={'business_id':b},headers=token(kind,'customer','other@example.com'),
                      json={'summary':'Unauthorized'}).status_code==404
    with SF.begin() as db:
        ap=db.scalars(select(Appointment).where(Appointment.reference==ref)).one()
        ap.status='cancelled'
    assert client.put(url,params={'business_id':b},headers=token(kind),
                      json={'notes':'Too late'}).status_code==409


def test_salon_old_haircut_notes_still_visible_in_universal_briefing(setup):
    client,SF,ids,auth=setup
    id_=make_booking(SF,ids,datetime.now(timezone.utc)+timedelta(days=2))
    with SF.begin() as db:
        db.add(BookingHaircutPreference(appointment_id=id_,style='fade',
                preferred_length='short',notes='Keep a longer fringe'))
    read=client.get('/api/appointments/SS-RECOV/service-intake',
                    params={'business_id':ids['a']},headers=auth('customer'))
    assert read.status_code==200,read.text
    assert read.json()['intake']['answers']['desired_style']=='fade'
    brief=client.get('/api/admin/appointments/SS-RECOV/service-briefing',
                     params={'business_id':ids['a']},headers=auth('admin'))
    assert brief.status_code==200 and brief.json()['intake']['notes']=='Keep a longer fringe'


def test_service_intake_survives_cross_branch_recovery(setup):
    client,SF,ids,auth=setup
    id_=make_booking(SF,ids,datetime.now(timezone.utc)+timedelta(days=2))
    answer={'summary':'Low taper','answers':{'desired_style':'taper'}}
    put=client.put('/api/appointments/SS-RECOV/service-intake',
                   params={'business_id':ids['a']},headers=auth('customer'),json=answer)
    assert put.status_code==200,put.text
    with SF.begin() as db:
        ap=db.get(Appointment,id_)
        db.add(RecoveryEvent(appointment_id=ap.id,from_business_id=ids['a'],to_business_id=ids['b'],
            from_service_id=ids['sa'],to_service_id=ids['sb'],
            from_staff_id=ids['pa'],to_staff_id=ids['pb'],
            previous_starts_at=ap.starts_at,new_starts_at=ap.starts_at,
            reason='branch_transfer',actor='auto_engine'))
        ap.business_id=ids['b'];ap.service_id=ids['sb'];ap.staff_id=ids['pb']
    owner_read=client.get('/api/appointments/SS-RECOV/service-intake',
                          params={'business_id':ids['a']},headers=auth('customer'))
    assert owner_read.status_code==200
    assert owner_read.json()['intake']==answer|{"notes":""}
    assert client.get('/api/admin/appointments/SS-RECOV/service-briefing',
          params={'business_id':ids['a']},headers=auth('admin')).status_code==404
    destination=client.get('/api/admin/appointments/SS-RECOV/service-briefing',
          params={'business_id':ids['b']},headers=auth('admin',business_id=ids['b']))
    assert destination.status_code==200
    assert destination.json()['intake']['summary']=='Low taper'
    restricted={'Authorization': 'Bearer '+issue_token('admin','Restricted','admin@example.com',ids['a'],[ids['a']])}
    assert client.get('/api/admin/appointments/SS-RECOV/service-briefing',
          params={'business_id':ids['b']},headers=restricted).status_code==403


def test_sqlite_migration_0008_additive_table():
    migration_path=Path(__file__).resolve().parents[1]/'migrations/versions/0008_general_service_intake.py'
    spec=importlib.util.spec_from_file_location('migration_intake_0008',migration_path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision=='0007_haircut_preferences'
    engine=create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[t for t in Base.metadata.sorted_tables
                                            if t.name!='booking_service_intakes'])
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        assert 'booking_service_intakes' in inspect(conn).get_table_names()
        cols={v['name'] for v in inspect(conn).get_columns('booking_service_intakes')}
        assert {'appointment_id','category','summary','notes','answers','created_at','updated_at'}<=cols
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        assert 'booking_service_intakes' not in inspect(conn).get_table_names()
    engine.dispose()
