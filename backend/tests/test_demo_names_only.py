"""Focused tests for demo-name repair, run against SQLite only."""
from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Appointment, Business, Staff
from demo_showcase_seed import seed_showcase
from demo_finalize_seed import seed_final_demo
from demo_identity_names import STAFF_DISPLAY_NAMES
from rename_demo_people import propose_renames


def test_unique_labels_and_reseed_stability():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Factory.begin() as db:
        now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
        seed_showcase(db, now)
        seed_final_demo(db, now, 150)
        original_ids = [r.id for r in db.scalars(select(Appointment).where(Appointment.reference.like('SS-WF-%')))]
        roster_ids = [r.id for r in db.scalars(select(Staff))]
        staff = list(db.scalars(select(Staff)))
        assert len(staff) == 60
        assert len({s.name for s in staff}) == 60
        assert set(s.name for s in staff) == {name for pool in STAFF_DISPLAY_NAMES.values() for name in pool.values()}
        bookings = [r for r in db.scalars(select(Appointment).where(Appointment.reference.like('SS-WF-%')))]
        assert len(bookings) == 150
        assert len({r.customer_name for r in bookings}) == 100
        assert all(not r.customer_name.startswith('Demo Customer') for r in bookings)
        changes, counters = propose_renames(db)
        # Showcase scenario customers originally inserted under friendly names too.
        assert counters['staff'] == 0
        assert counters['bookings'] == 0
        assert len(changes) == 0
        seed_showcase(db, now)
        seed_final_demo(db, now, 150)
        assert roster_ids == [r.id for r in db.scalars(select(Staff))]
        assert original_ids == [r.id for r in db.scalars(select(Appointment).where(Appointment.reference.like('SS-WF-%')))]
    engine.dispose()


def test_legacy_names_rename_without_touching_non_demo():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Factory.begin() as db:
        now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
        seed_showcase(db, now)
        seed_final_demo(db, now, 12)
        salon = db.scalar(select(Business).where(Business.demo_key == 'showcase_salon_a'))
        staff = db.scalar(select(Staff).where(Staff.business_id == salon.id))
        staff.name = next(iter(STAFF_DISPLAY_NAMES['showcase_salon_a']))  # restore legacy seed label
        booking = db.scalar(select(Appointment).where(Appointment.reference == 'SS-WF-0001'))
        booking.customer_name = 'Demo Customer 001'
        changes, counts = propose_renames(db)
        assert counts['staff'] == 1
        assert counts['bookings'] == 1
        for obj, new in changes:
            if isinstance(obj, Appointment):
                obj.customer_name = new
            else:
                obj.name = new
        db.flush()
        assert propose_renames(db)[1]['staff'] == 0
        assert propose_renames(db)[1]['bookings'] == 0
        original_count = len(list(db.scalars(select(Staff))))
        seed_showcase(db, now)
        seed_final_demo(db, now, 12)
        assert len(list(db.scalars(select(Staff)))) == original_count
    engine.dispose()
