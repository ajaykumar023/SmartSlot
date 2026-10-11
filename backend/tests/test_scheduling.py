from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Availability, Business, BusinessHours, Service, Staff, StaffService
from app.scheduling import candidate_slots


@pytest.mark.parametrize("category,title", [
    ("salon", "Stylist"), ("clinic", "Doctor"),
    ("repair_center", "Technician"), ("consultant", "Consultant"),
])
def test_candidate_slots_are_industry_labeled_and_business_scoped(category, title):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        day = datetime.now(timezone.utc).date() + timedelta(days=2)
        day += timedelta(days=(0 - day.weekday()) % 7)
        business = Business(name="Demo", category=category, description="", timezone="UTC", active=True,
                            is_demo=True, default_buffer_minutes=5)
        other = Business(name="Other", category="salon", description="", timezone="UTC", active=True,
                         is_demo=True, default_buffer_minutes=0)
        db.add_all([business, other])
        db.flush()
        service = Service(business_id=business.id, name="Appointment", description="", duration_minutes=30,
                          buffer_minutes=5, active=True)
        other_service = Service(business_id=other.id, name="Other service", description="", duration_minutes=30,
                                buffer_minutes=0, active=True)
        staff = Staff(business_id=business.id, name="Professional", title=title, active=True)
        other_staff = Staff(business_id=other.id, name="Other professional", title="Stylist", active=True)
        db.add_all([service, other_service, staff, other_staff])
        db.flush()
        db.add_all([
            StaffService(staff_id=staff.id, service_id=service.id),
            StaffService(staff_id=other_staff.id, service_id=other_service.id),
            BusinessHours(business_id=business.id, weekday=day.weekday(), opens_at=time(9), closes_at=time(12)),
            Availability(business_id=business.id, staff_id=staff.id, weekday=day.weekday(), start_time=time(9), end_time=time(12)),
        ])
        db.commit()

        slots = candidate_slots(db, business, service.id, day, day)
        assert slots
        assert all(slot["staff_title"] == title for slot in slots)
        assert all(slot["business_id"] == business.id for slot in slots)
        assert candidate_slots(db, business, other_service.id, day, day) == []
