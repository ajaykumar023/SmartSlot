"""Haircut notes: authorization, legacy bookings, booking creation, recovery handoff.
SQLite integration only; PostgreSQL migrations still require live verification.
"""
from datetime import datetime, time, timedelta, timezone
from sqlalchemy import select
from app.models import Appointment, BookingHaircutPreference, RecoveryEvent
from tests.test_recovery import setup, make_booking, add_unavailability, consent
from tests.test_member4_flow import ctx, booking
from app.auth import issue_token


def url(ref):
    return f'/api/appointments/{ref}/haircut-preferences'


def test_existing_booking_defaults_to_no_preferences(setup):
    client, SF, ids, auth = setup
    make_booking(SF, ids, datetime.now(timezone.utc)+timedelta(days=2))
    customer = auth('customer')
    response = client.get(url('SS-RECOV'), params={'business_id':ids['a']}, headers=customer)
    assert response.status_code == 200, response.text
    assert response.json()['preferences'] is None
    brief = client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                       params={'business_id':ids['a']}, headers=auth('admin'))
    assert brief.status_code == 200 and brief.json()['preferences'] is None


def test_update_and_briefing_with_customer_specific_details(setup):
    client, SF, ids, auth = setup
    make_booking(SF, ids, datetime.now(timezone.utc)+timedelta(days=2))
    customer=auth('customer')
    content={'style':'taper','preferred_length':'medium',
             'notes':'Low taper; keep the fringe. Please confirm the final length.'}
    update=client.put(url('SS-RECOV'),params={'business_id':ids['a']},
                      headers=customer,json=content)
    assert update.status_code==200,update.text
    assert update.json()['preferences']==content
    briefing=client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                        params={'business_id':ids['a']},headers=auth('admin'))
    assert briefing.status_code == 200,briefing.text
    assert briefing.json()['preferences']==content
    assert briefing.json()['staff_name']=='Alex'
    assert 'customer_email' not in briefing.json()
    assert briefing.json()['service_duration_minutes']==30
    with SF() as db:
        assert len(db.scalars(select(BookingHaircutPreference)).all()) == 1
    # Full replacement rather than accidentally leaving stale notes.
    updated=client.put(url('SS-RECOV'),params={'business_id':ids['a']},headers=customer,
                       json={'style':'trim','preferred_length':'short','notes':''})
    assert updated.status_code==200
    with SF() as db:
        row=db.scalars(select(BookingHaircutPreference)).one()
        assert row.notes=='' and row.style=='trim'


def test_no_cross_customer_or_cross_branch_access(setup):
    client,SF,ids,auth=setup
    make_booking(SF,ids,datetime.now(timezone.utc)+timedelta(days=2))
    stranger=auth('customer','someoneelse@example.com')
    # Demo admin login intentionally grants all demo businesses. Forge a signed
    # token with explicit one-branch scope to test endpoint authorization.
    admin_b={'Authorization': 'Bearer '+issue_token('admin','Restricted','admin@smartslot.demo',ids['b'],[ids['b']])}
    assert client.get(url('SS-RECOV'),params={'business_id':ids['a']},headers=stranger).status_code==404
    assert client.put(url('SS-RECOV'),params={'business_id':ids['a']},headers=stranger,
                      json={'notes':'Forbidden'}).status_code==404
    assert client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                      params={'business_id':ids['a']},headers=admin_b).status_code==403
    assert client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                      params={'business_id':ids['b']},headers=admin_b).status_code==404
    assert client.get(url('SS-RECOV'),params={'business_id':ids['a']}).status_code==401


def test_validation_rejects_oversized_notes_unsupported_photos_and_invalid_style(setup):
    client,SF,ids,auth=setup
    make_booking(SF,ids,datetime.now(timezone.utc)+timedelta(days=2))
    who=auth('customer')
    for payload in ({'notes':'a'*801}, {'style':'mohawk'},
                    {'reference_image_url':'https://example.com/photo.jpg'}):
        result=client.put(url('SS-RECOV'),params={'business_id':ids['a']},
                          headers=who,json=payload)
        assert result.status_code==422,(payload.keys(),result.text)
    with SF() as db:
        assert db.scalars(select(BookingHaircutPreference)).all()==[]


def test_cancelled_or_started_booking_cannot_update(setup):
    client,SF,ids,auth=setup
    ap_id=make_booking(SF,ids,datetime.now(timezone.utc)+timedelta(days=2))
    customer=auth('customer')
    with SF.begin() as db:
        db.get(Appointment,ap_id).status='cancelled'
    result=client.put(url('SS-RECOV'),params={'business_id':ids['a']},headers=customer,
                      json={'style':'fade'})
    assert result.status_code==409
    with SF.begin() as db:
        book=db.get(Appointment,ap_id)
        book.status='confirmed';book.starts_at=datetime.now(timezone.utc)-timedelta(minutes=1)
    result=client.put(url('SS-RECOV'),params={'business_id':ids['a']},headers=customer,
                      json={'style':'fade'})
    assert result.status_code==409


def test_preferences_follow_same_branch_staff_substitution(setup):
    client,SF,ids,auth=setup
    start=datetime.now(timezone.utc)+timedelta(days=2)
    make_booking(SF,ids,start)
    customer=auth('customer')
    client.put(url('SS-RECOV'),params={'business_id':ids['a']},headers=customer,
               json={'style':'fade','preferred_length':'short','notes':'Low fade, not high'} )
    assert consent(client,ids,auth).status_code==200
    result=client.post(f'/api/admin/staff/{ids["pa"]}/absences',
                       params={'business_id':ids['a']},headers=auth('admin'),
                       json={'starts_at':(start-timedelta(minutes=2)).isoformat(),
                             'ends_at':(start+timedelta(minutes=35)).isoformat(),'reason':'break'})
    assert result.status_code==201,result.text
    assert result.json()['reassigned_appointment_references']==['SS-RECOV']
    brief=client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                     params={'business_id':ids['a']},headers=auth('admin')).json()
    assert brief['staff_name']=='Priya'
    assert brief['preferences']['notes']=='Low fade, not high'


def test_preferences_follow_cross_branch_handoff_and_scope(setup):
    client,SF,ids,auth=setup
    appointment_id=make_booking(SF,ids,datetime.now(timezone.utc)+timedelta(days=2))
    customer=auth('customer')
    put=client.put(url('SS-RECOV'),params={'business_id':ids['a']},headers=customer,
                   json={'style':'layers','notes':'Keep some layers'})
    assert put.status_code==200
    with SF.begin() as db:
        ap=db.get(Appointment,appointment_id)
        db.add(RecoveryEvent(appointment_id=ap.id,from_business_id=ids['a'],to_business_id=ids['b'],
            from_service_id=ids['sa'],to_service_id=ids['sb'],
            from_staff_id=ids['pa'],to_staff_id=ids['pb'],
            previous_starts_at=ap.starts_at,new_starts_at=ap.starts_at,reason='branch_transfer',actor='auto_engine'))
        ap.business_id=ids['b'];ap.service_id=ids['sb'];ap.staff_id=ids['pb']
    original_session_get=client.get(url('SS-RECOV'),params={'business_id':ids['a']},headers=customer)
    assert original_session_get.status_code==200,original_session_get.text
    assert original_session_get.json()['preferences']['style']=='layers'
    admin_a=auth('admin')
    admin_b=auth('admin',business_id=ids['b'])
    assert client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                      params={'business_id':ids['a']},headers=admin_a).status_code==404
    brief=client.get('/api/admin/appointments/SS-RECOV/stylist-briefing',
                     params={'business_id':ids['b']},headers=admin_b)
    assert brief.status_code==200
    assert brief.json()['preferences']['notes']=='Keep some layers'


def test_booking_endpoint_accepts_optional_nested_preferences(setup):
    client,SF,ids,auth=setup
    customer=auth('customer')
    day=(datetime.now(timezone.utc)+timedelta(days=3)).date()
    starts=datetime.combine(day,time(10,0),timezone.utc)
    body={'service_id':ids['sa'],'starts_at':starts.isoformat(),
          'name':'Alex','email':'alex@example.com',
          'haircut_preferences':{'style':'fade','preferred_length':'short','notes':'Reference: low fade'}}
    response=client.post('/api/appointments',params={'business_id':ids['a']},headers=customer,json=body)
    assert response.status_code==201,response.text
    ref=response.json()['reference']
    fetched=client.get(url(ref),params={'business_id':ids['a']},headers=customer)
    assert fetched.status_code==200 and fetched.json()['preferences']['style']=='fade'
    with SF() as db:
        assert len(db.scalars(select(BookingHaircutPreference)).all())==1


def test_auto_book_forwards_preferences(setup):
    client,SF,ids,auth=setup
    customer=auth('customer')
    day=(datetime.now(timezone.utc)+timedelta(days=3)).date()
    response=client.post('/api/appointments/auto-book',
                         params={'business_id':ids['a']},headers=customer,
                         json={'service_id':ids['sa'],'preferred_date':day.isoformat(),
                               'name':'Alex','email':'alex@example.com',
                               'haircut_preferences':{'style':'trim','notes':'Only a little off'}})
    assert response.status_code==201,response.text
    fetched=client.get(url(response.json()['reference']),
                       params={'business_id':ids['a']},headers=customer)
    assert fetched.json()['preferences']['notes']=='Only a little off'


def test_non_salon_booking_rejects_haircut_details(ctx):
    client,SF,ids,login=ctx
    customer=login('customer','original@example.com')
    future=datetime.now(timezone.utc)+timedelta(days=2)
    ref,_,id_=booking(SF,ids,future)
    update=client.put(url(ref),params={'business_id':ids[0]},headers=customer,
                      json={'notes':'Not for healthcare'})
    assert update.status_code==422
    get=client.get(url(ref),params={'business_id':ids[0]},headers=customer)
    assert get.status_code==422


def test_new_clinic_booking_cannot_attach_haircut_preferences(ctx):
    client,SF,ids,login=ctx
    customer=login('customer','original@example.com')
    day=(datetime.now(timezone.utc)+timedelta(days=3)).date()
    starts=datetime.combine(day,time(12),timezone.utc)
    response=client.post('/api/appointments',params={'business_id':ids[0]},headers=customer,
                         json={'service_id':ids[2], 'starts_at':starts.isoformat(),
                               'name':'Original','email':'original@example.com',
                               'haircut_preferences':{'style':'fade'}})
    assert response.status_code == 422,response.text
    with SF() as db:
        assert db.scalars(select(BookingHaircutPreference)).all()==[]
        assert db.scalars(select(Appointment)).all()==[]


def test_sqlite_migration_0007_creates_constraints():
    """Sanity-check the additive migration without depending on live PostgreSQL."""
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    from app.database import Base

    migration_path=Path(__file__).resolve().parents[1]/'migrations/versions/0007_haircut_preferences.py'
    spec=importlib.util.spec_from_file_location('migration_haircut_0007',migration_path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision=='0006_smart_recovery'
    engine=create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[t for t in Base.metadata.sorted_tables
                                            if t.name!='booking_haircut_preferences'])
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert 'booking_haircut_preferences' in inspect(conn).get_table_names()
        columns={col['name'] for col in inspect(conn).get_columns('booking_haircut_preferences')}
        assert {'appointment_id','style','preferred_length','notes','created_at','updated_at'}<=columns
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert 'booking_haircut_preferences' not in inspect(conn).get_table_names()
    engine.dispose()
