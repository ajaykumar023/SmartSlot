"""Tests use isolated SQLite only; do NOT modify local PostgreSQL."""
from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest
from fastapi import HTTPException

from app.database import Base
from app.models import Appointment, Business, Staff, StaffAbsence, StaffService
from demo_showcase_seed import seed_showcase
from demo_customers_seed import seed_customers
from demo_finalize_seed import PLAN, seed_final_demo
from app.demo_ops_api import summary, team

@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with Session() as session:
            yield session
    finally:
        engine.dispose()

NOW = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)


def test_missing_showcase_refuses(db):
    with pytest.raises(ValueError, match='showcase'):
        seed_final_demo(db, NOW)
    assert db.query(Staff).count() == 0


def test_60_staff_and_150_bookings_idempotent(db):
    seed_showcase(db, NOW)
    seed_customers(db, NOW)
    first = seed_final_demo(db, NOW)
    assert sum(row['employees_total'] for row in first['businesses'].values()) == 60
    assert first['distinct_customer_emails'] == 100
    assert first['newly_seeded_bookings_or_existing'] == 150
    assert sum(row['support_staff'] for row in first['businesses'].values()) == 23
    # Calling twice preserves appointments and staff records.
    before = (db.query(Staff).count(), db.query(Appointment).count())
    second = seed_final_demo(db, NOW)
    assert before == (db.query(Staff).count(), db.query(Appointment).count())
    assert second['reroute_demo_absences_created'] == 0
    for key, size in first['businesses'].items():
        assert size['employees_total'] == PLAN[key]['target']


def test_support_staff_unqualified_and_route_demo_preserved(db):
    seed_showcase(db, NOW)
    info = seed_final_demo(db, NOW, 10)
    assert info['reroute_demo_absences_created'] == 7
    salon = db.scalar(select(Business).where(Business.demo_key == 'showcase_salon_a'))
    staff = db.scalars(select(Staff).where(Staff.business_id == salon.id)).all()
    qualified = {sid for sid in db.scalars(select(StaffService.staff_id)).all()}
    helpers = [row for row in staff if 'Receptionist' in row.title or 'assistant' in row.title or 'manager' in row.title]
    assert len(helpers) == 5
    assert all(member.id not in qualified for member in helpers)
    absences = db.scalars(select(StaffAbsence).where(StaffAbsence.source == 'workforce_route_demo')).all()
    assert len(absences) == 7


def test_admin_ops_scope(db):
    seed_showcase(db, NOW)
    seed_final_demo(db, NOW, 5)
    salon = db.scalar(select(Business).where(Business.demo_key == 'showcase_salon_a'))
    valid = {'role':'admin','business_ids':[salon.id]}
    result = summary(salon.id, NOW.date(), valid, db)
    assert result['staff']['total'] == 14
    assert len(team(salon.id, NOW.date(), valid, db)['team']) == 14
    with pytest.raises(HTTPException) as exc:
        summary(salon.id, NOW.date(), {'role':'admin','business_ids':[]}, db)
    assert exc.value.status_code == 403
