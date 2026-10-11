"""Idempotently add four fictional industry demo profiles and their opening hours."""
from datetime import time
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.models import Availability, Business, BusinessHours, Service, Staff, StaffService


PROFILES = [
    {"key": "salon", "name": "Aether Studio", "category": "salon", "description": "A neighborhood studio for appointments in hair care and styling.", "timezone": "Asia/Kolkata", "hours": (time(9), time(18)), "days": range(6),
     "services": [("Haircut", "A tailored cut and finish.", 45), ("Styling", "A styling appointment for a special day or everyday look.", 30), ("Hair treatment", "A restorative hair-care session.", 60)],
     "staff": [("Mira Shah", "Stylist", ["Haircut", "Styling", "Hair treatment"]), ("Dev Mehta", "Senior Stylist", ["Haircut", "Styling"])]},
    {"key": "clinic", "name": "Northstar Family Clinic", "category": "clinic", "description": "Fictional primary-care clinic for general appointment scheduling demos.", "timezone": "Asia/Kolkata", "hours": (time(8, 30), time(17)), "days": range(5),
     "services": [("General consultation", "A scheduled general consultation. No medical notes are collected.", 30), ("Follow-up consultation", "A follow-up appointment with a clinician.", 20), ("Routine check-up", "A routine check-up appointment.", 45)],
     "staff": [("Dr. Anika Rao", "Doctor", ["General consultation", "Follow-up consultation", "Routine check-up"]), ("Dr. Omar Sen", "Clinician", ["General consultation", "Follow-up consultation"])]},
    {"key": "repair_center", "name": "FixPoint Repair Center", "category": "repair_center", "description": "Fictional device repair desk for scheduled assessment and maintenance.", "timezone": "Asia/Kolkata", "hours": (time(9), time(18)), "days": range(6),
     "services": [("Laptop diagnostics", "A scheduled diagnostic assessment; booking does not mean repair is complete.", 60), ("Phone repair assessment", "An appointment to assess a phone repair request.", 30), ("Device maintenance", "A longer appointment for device maintenance.", 90)],
     "staff": [("Ishan Verma", "Technician", ["Laptop diagnostics", "Device maintenance"]), ("Ritu Das", "Repair technician", ["Phone repair assessment", "Laptop diagnostics"])]},
    {"key": "consultant", "name": "Northstar Consulting", "category": "consultant", "description": "Fictional consulting practice offering focused working sessions.", "timezone": "Asia/Kolkata", "hours": (time(9, 30), time(17, 30)), "days": range(5),
     "services": [("Initial consultation", "A first structured conversation about goals and next steps.", 60), ("Follow-up session", "A focused follow-up working session.", 45), ("Project review", "A longer project review appointment.", 90)],
     "staff": [("Nisha Kapoor", "Consultant", ["Initial consultation", "Follow-up session", "Project review"]), ("Arjun Bose", "Senior consultant", ["Initial consultation", "Project review"])]},
]


def seed():
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        for profile in PROFILES:
            business = db.scalar(select(Business).where(Business.demo_key == profile["key"]))
            if not business and profile["key"] == "salon":
                # Migration explicitly identifies the original id=1 demo profile; never infer from its name.
                business = db.get(Business, 1)
                if business and business.is_demo:
                    business.demo_key = "salon"
            if not business:
                business = Business(demo_key=profile["key"], name=profile["name"], category=profile["category"],
                    description=profile["description"], timezone=profile["timezone"], is_demo=True, active=True)
                db.add(business)
                db.flush()
            service_rows = {}
            for name, description, duration in profile["services"]:
                service = db.scalar(select(Service).where(Service.business_id == business.id, Service.name == name))
                if not service:
                    service = Service(business_id=business.id, name=name, description=description, duration_minutes=duration, buffer_minutes=0, active=True)
                    db.add(service)
                    db.flush()
                service_rows[name] = service
            for name, title, qualification_names in profile["staff"]:
                staff = db.scalar(select(Staff).where(Staff.business_id == business.id, Staff.name == name))
                if not staff:
                    staff = Staff(business_id=business.id, name=name, title=title, active=True)
                    db.add(staff)
                    db.flush()
                for service_name in qualification_names:
                    link = db.get(StaffService, (staff.id, service_rows[service_name].id))
                    if not link:
                        db.add(StaffService(staff_id=staff.id, service_id=service_rows[service_name].id))
                for weekday in profile["days"]:
                    shift = db.scalar(select(Availability).where(Availability.business_id == business.id,
                        Availability.staff_id == staff.id, Availability.weekday == weekday))
                    if not shift:
                        db.add(Availability(business_id=business.id, staff_id=staff.id, weekday=weekday,
                            start_time=profile["hours"][0], end_time=profile["hours"][1]))
            for weekday in range(7):
                hours = db.scalar(select(BusinessHours).where(BusinessHours.business_id == business.id, BusinessHours.weekday == weekday))
                if not hours and weekday in profile["days"]:
                    db.add(BusinessHours(business_id=business.id, weekday=weekday,
                        opens_at=profile["hours"][0], closes_at=profile["hours"][1]))
    print("Four fictional SmartSlot industry demos are ready. Existing non-demo businesses and records were not deleted or overwritten.")


if __name__ == "__main__":
    seed()
