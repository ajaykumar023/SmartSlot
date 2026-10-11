"""Additive seed fixture tests; never touches live PostgreSQL."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Appointment, BookingServiceIntake, WaitlistEntry, Organization, Business
from demo_showcase_seed import seed_showcase
from demo_customers_seed import CUSTOMERS, WAITLIST_CUSTOMERS, seed_customers


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as session:
            yield session
    finally:
        engine.dispose()


def test_refuses_to_run_without_original_showcase(db):
    with pytest.raises(ValueError, match="Run demo_showcase_seed"):
        seed_customers(db, datetime(2026, 10, 12, 9, tzinfo=timezone.utc))
    assert not db.scalars(select(Appointment)).all()


def test_creates_bookings_and_waitlist_across_four_categories(db):
    now = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    seed_showcase(db, now)
    result = seed_customers(db, now)
    assert len(result["customers"]) == len(CUSTOMERS) == 15
    assert len(result["waitlist_customers"]) == len(WAITLIST_CUSTOMERS) == 3
    assert all(item["email"].endswith("@aetherx.example") for item in result["customers"])
    assert {p.category for p in db.scalars(select(BookingServiceIntake)).all()} == {"salon", "clinic", "repair_center", "consultant"}
    assert len([row for row in db.scalars(select(Appointment)).all() if row.reference.startswith("SS-CU-")]) == 15
    assert len([row for row in db.scalars(select(WaitlistEntry)).all() if row.customer_email in {x[1] for x in WAITLIST_CUSTOMERS}]) == 3


def test_repeat_seed_does_not_reset_customer_cancellations(db):
    now = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    seed_showcase(db, now)
    seed_customers(db, now)
    row = db.scalar(select(Appointment).where(Appointment.reference == "SS-CU-0001"))
    row.status = "cancelled"
    db.flush()
    first_id = row.id
    seed_customers(db, now)
    rows = db.scalars(select(Appointment).where(Appointment.reference == "SS-CU-0001")).all()
    assert len(rows) == 1
    assert rows[0].id == first_id and rows[0].status == "cancelled"


def test_does_not_write_to_unrelated_businesses(db):
    now = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    seed_showcase(db, now)
    seed_customers(db, now)
    org = db.scalar(select(Organization).where(Organization.slug == "aetherx-showcase-v1"))
    valid = {b.id for b in db.scalars(select(Business).where(Business.organization_id == org.id))}
    for entry in db.scalars(select(Appointment).where(Appointment.reference.like("SS-CU-%"))).all():
        assert entry.business_id in valid
