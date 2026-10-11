"""AETHERX deterministic fictional demo fixtures for Phase 4 (migration 0008).

Run from backend/ after migrating and backing up PostgreSQL:
    python demo_showcase_seed.py                 # dry preview; zero database writes
    $env:AETHERX_DEMO_WRITE='YES'
    python demo_showcase_seed.py --apply         # explicitly opt into demo writes

Only creates namespaced DEMO businesses, staff, bookings, consent and absences.
Never alters existing ordinary bookings, existing demo profiles, or existing GPS.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Organization, Business, BusinessHours, Service, Staff, StaffService,
    Availability, Appointment, BookingServiceIntake, RecoveryPolicy,
    ServiceTransfer, StaffAbsence, WaitlistEntry,
)
from app.qr import token_hash
from demo_identity_names import employee_name, SCENARIO_CUSTOMERS

DEMO_ORG_SLUG = "aetherx-showcase-v1"
TZ = ZoneInfo("Asia/Kolkata")

# These are fictional locations and 24/7 availability solely for isolated testing.
# Never present them as real businesses, practitioners, or verified operating hours.
PROFILES = {
    "salon_a": {
        "demo_key": "showcase_salon_a", "name": "AETHERX Showcase Studio A [DEMO]", "category": "salon",
        "latitude": 12.9716, "longitude": 77.5946,
        "service": "Haircut demonstration", "staff": ("Demo Stylist A", "Demo Stylist B"),
        "intake": {"summary": "Low taper cut", "notes": "Confirm desired length on arrival",
                   "answers": {"desired_style": "Low taper fade", "preferred_length": "medium"}},
    },
    "salon_b": {
        "demo_key": "showcase_salon_b", "name": "AETHERX Showcase Studio B [DEMO]", "category": "salon",
        "latitude": 12.9750, "longitude": 77.6100,
        "service": "Haircut demonstration", "staff": ("Demo Backup Stylist",),
        "intake": None,
    },
    "clinic": {
        "demo_key": "showcase_clinic", "name": "AETHERX Showcase Clinic [DEMO]", "category": "clinic",
        "latitude": None, "longitude": None,
        "service": "General appointment demonstration", "staff": ("Demo Clinician",),
        "intake": {"summary": "Routine visit", "notes": "Fictional nonclinical scheduling data only",
                   "answers": {"visit_reason": "Routine consultation", "visit_type": "First visit"}},
    },
    "repair": {
        "demo_key": "showcase_repair", "name": "AETHERX Showcase Repair [DEMO]", "category": "repair_center",
        "latitude": None, "longitude": None,
        "service": "Laptop assessment demonstration", "staff": ("Demo Technician",),
        "intake": {"summary": "Laptop display diagnosis", "notes": "Do not perform repairs without authorization",
                   "answers": {"item_type": "Laptop", "reported_issue": "Flickering screen"}},
    },
    "consulting": {
        "demo_key": "showcase_consult", "name": "AETHERX Showcase Consulting [DEMO]", "category": "consultant",
        "latitude": None, "longitude": None,
        "service": "Project consultation demonstration", "staff": ("Demo Consultant",),
        "intake": {"summary": "Review a prototype", "notes": "Discuss timeline and scope",
                   "answers": {"consultation_goal": "Prototype feedback", "project_context": "Hackathon MVP"}},
    },
}

SCENARIOS = (
    ("local", "salon_a", "SS-DM-LOCAL", "Demo Local Recovery", "demo.local@aetherx.example", 0, "confirmed"),
    ("route", "salon_a", "SS-DM-ROUTE", "Demo Branch Recovery", "demo.route@aetherx.example", 60, "confirmed"),
    ("clinic", "clinic", "SS-DM-CLIN", "Demo Clinic Customer", "demo.clinic@aetherx.example", 30, "confirmed"),
    ("repair", "repair", "SS-DM-REPR", "Demo Repair Customer", "demo.repair@aetherx.example", 30, "confirmed"),
    ("consulting", "consulting", "SS-DM-CONS", "Demo Consulting Customer", "demo.consult@aetherx.example", 30, "confirmed"),
    ("cancelled", "salon_b", "SS-DM-CANCEL", "Demo Cancelled Customer", "demo.cancel@aetherx.example", 150, "cancelled"),
)


def round_up_half_hour(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    return dt + timedelta(minutes=(30 - dt.minute % 30) % 30)


def appointment_anchor(now_utc: datetime) -> datetime:
    """Choose a near-future time in Asia/Kolkata without spanning midnight.

    The two recovery bookings are 60 minutes apart; day shifts maintain
    a realistic test of the app's same-calendar-day constraints.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    local = now_utc.astimezone(TZ)
    proposed = round_up_half_hour(local + timedelta(minutes=100))
    if proposed.hour >= 21 or proposed.date() != local.date():
        proposed = datetime.combine(local.date() + timedelta(days=1), time(0, 30), TZ)
    return proposed


def _ensure_business(db: Session, key: str, org: Organization):
    profile = PROFILES[key]
    business = db.scalar(select(Business).where(Business.demo_key == profile["demo_key"]))
    if business:
        if (not business.is_demo or business.category != profile["category"] or
                business.organization_id != org.id):
            raise ValueError(f"Refusing to modify non-showcase business: {profile['demo_key']}")
    else:
        business = Business(
            demo_key=profile["demo_key"], name=profile["name"], category=profile["category"],
            description="SYNTHETIC showcase. Never use as a real booking location.",
            timezone="Asia/Kolkata", organization_id=org.id, is_demo=True, active=True,
            latitude=profile["latitude"], longitude=profile["longitude"],
        )
        db.add(business)
        db.flush()
    service = db.scalar(select(Service).where(Service.business_id == business.id, Service.name == profile["service"]))
    if not service:
        service = Service(business_id=business.id, name=profile["service"], description="DEMO only",
                          duration_minutes=30, buffer_minutes=0, price=200, active=True)
        db.add(service)
        db.flush()
    people = []
    for name in profile["staff"]:
        display_name = employee_name(profile["demo_key"], name)
        matches = list(db.scalars(select(Staff).where(
            Staff.business_id == business.id, Staff.name.in_((name, display_name)))))
        if len(matches) > 1:
            raise ValueError(f"Duplicate demo staff identities for {name}; inspect rows manually")
        person = matches[0] if matches else None
        if not person:
            person = Staff(business_id=business.id, name=display_name, title="Fictional professional", active=True)
            db.add(person)
            db.flush()
        elif person.name != display_name:
            person.name = display_name
        if not db.get(StaffService, (person.id, service.id)):
            db.add(StaffService(staff_id=person.id, service_id=service.id))
        for weekday in range(7):
            shift = db.scalar(select(Availability).where(Availability.staff_id == person.id,
                Availability.business_id == business.id, Availability.weekday == weekday))
            if not shift:
                db.add(Availability(business_id=business.id, staff_id=person.id,
                                    weekday=weekday, start_time=time(0, 0), end_time=time(23, 59)))
        people.append(person)
    for weekday in range(7):
        bh = db.scalar(select(BusinessHours).where(BusinessHours.business_id == business.id,
                                                    BusinessHours.weekday == weekday))
        if not bh:
            db.add(BusinessHours(business_id=business.id, weekday=weekday,
                                 opens_at=time(0, 0), closes_at=time(23, 59)))
    return business, service, people


def seed_showcase(db: Session, now_utc: datetime | None = None) -> dict:
    """Write synthetic demo fixtures into an already-migrated, isolated DB session.

    Caller controls commit/rollback. Repeated runs do not reset moved appointments
    or customer preferences. No external routing requests or notifications sent.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
    if not org:
        org = Organization(slug=DEMO_ORG_SLUG, name="AETHERX Showcase [FICTIONAL]")
        db.add(org)
        db.flush()
    locations = {key: _ensure_business(db, key, org) for key in PROFILES}
    src_business, src_service, src_staff = locations["salon_a"]
    dst_business, dst_service, _ = locations["salon_b"]
    link = db.scalar(select(ServiceTransfer).where(ServiceTransfer.source_service_id == src_service.id,
                                                   ServiceTransfer.target_service_id == dst_service.id))
    if not link:
        db.add(ServiceTransfer(organization_id=org.id, source_service_id=src_service.id,
                               target_service_id=dst_service.id, active=True))
    elif link.organization_id != org.id:
        raise ValueError("Existing transfer link belongs to a different organization")
    base = appointment_anchor(now_utc)
    result = {"businesses": {key: locations[key][0].id for key in PROFILES},
              "appointment_base_local": base.isoformat(), "scenarios": {},
              "note": "FICTIONAL seeded events, not real API traffic, attendance, or delivered notifications"}
    for label, business_key, reference, name, email, offset, status in SCENARIOS:
        business, service, people = locations[business_key]
        name = SCENARIO_CUSTOMERS.get(email, name)
        # A previously transferred appointment now belongs to the destination branch.
        # Look for the specific demo identity across branches so rerunning the seed
        # never creates a duplicate booking at its original branch.
        existing = db.scalar(select(Appointment).where(Appointment.reference == reference,
                                                     Appointment.customer_email == email))
        occupied = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
                                                     Appointment.reference == reference))
        if occupied and occupied.customer_email != email:
            raise ValueError(f"Reserved demo reference {reference} is in use by another customer")
        if existing:
            saved_business = db.get(Business, existing.business_id)
            if not saved_business or not saved_business.is_demo or saved_business.organization_id != org.id:
                raise ValueError("Demo reference belongs to an unrelated branch")
            booking = existing  # Preserve previously recovered bookings and booking identities.
        else:
            start = base + timedelta(minutes=offset)
            if start.date() != base.date():
                raise ValueError("Demo booking would cross midnight; choose another demo window")
            end = start + timedelta(minutes=service.duration_minutes)
            booking = Appointment(business_id=business.id, service_id=service.id,
                                  staff_id=people[0].id, customer_name=name,
                                  customer_email=email, reference=reference,
                                  qr_token_hash=token_hash(secrets.token_urlsafe(32)),
                                  starts_at=start.astimezone(timezone.utc),
                                  ends_at=end.astimezone(timezone.utc),
                                  duration_minutes=service.duration_minutes, buffer_minutes=0,
                                  status=status)
            db.add(booking)
            db.flush()
            if profile_intake := PROFILES[business_key]["intake"]:
                db.add(BookingServiceIntake(appointment_id=booking.id, category=business.category,
                                            summary=profile_intake["summary"],
                                            notes=profile_intake["notes"],
                                            answers=dict(profile_intake["answers"])))
            if label in ("local", "route"):
                db.add(RecoveryPolicy(appointment_id=booking.id,
                    allow_staff_substitution=True, allow_branch_transfer=(label == "route"),
                    max_delay_minutes=30))
        result["scenarios"][label] = {
            "business_id": booking.business_id, "reference": booking.reference,
            "email": booking.customer_email, "starts_at": booking.starts_at.isoformat(),
            "status": booking.status,
        }

    # Force a verified conflict for recovery demos without changing booking status.
    # Not a real staff absence, clearly tagged as synthetic and namespaced.
    source_start = db.scalar(select(Appointment).where(Appointment.reference == "SS-DM-LOCAL",
                                                      Appointment.customer_email == "demo.local@aetherx.example"))
    source_route = db.scalar(select(Appointment).where(Appointment.reference == "SS-DM-ROUTE",
                                                      Appointment.customer_email == "demo.route@aetherx.example"))
    if source_start and source_route and source_start.business_id == src_business.id and source_route.business_id == src_business.id:
        local_begin = source_start.starts_at
        route_begin = source_route.starts_at
        absences = [
            (src_staff[0], local_begin - timedelta(minutes=5), route_begin + timedelta(minutes=70)),
            (src_staff[1], route_begin - timedelta(minutes=5), route_begin + timedelta(minutes=70)),
        ]
        for person, from_dt, until_dt in absences:
            existing_absence = db.scalar(select(StaffAbsence).where(
                StaffAbsence.staff_id == person.id, StaffAbsence.source == "showcase_seed"))
            if not existing_absence:
                db.add(StaffAbsence(business_id=src_business.id, staff_id=person.id,
                                    starts_at=from_dt, ends_at=until_dt,
                                    reason="break", source="showcase_seed"))
    # A waiting customer exists but NO offer is manufactured: the existing waitlist
    # engine must establish real eligibility before reserving a released slot.
    existing_wait = db.scalar(select(WaitlistEntry).where(
        WaitlistEntry.business_id == src_business.id,
        WaitlistEntry.customer_email == "demo.wait@aetherx.example"))
    if not existing_wait:
        db.add(WaitlistEntry(business_id=src_business.id, service_id=src_service.id,
                             customer_email="demo.wait@aetherx.example", customer_name="Demo Waitlist Customer",
                             preferred_date=base.date().isoformat(), status="waiting"))
    db.flush()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually insert synthetic records. Requires AETHERX_DEMO_WRITE=YES.")
    args = parser.parse_args()
    if not args.apply:
        print("PREVIEW ONLY. No database writes.\n")
        print("Proposed businesses:")
        for profile in PROFILES.values():
            print(" -", profile["name"])
        print("\nScenarios:")
        for label, _, ref, *_ in SCENARIOS:
            print(" -", label, ref)
        print("\nTo insert after a database backup: set AETHERX_DEMO_WRITE=YES and use --apply.")
        return
    if os.environ.get("AETHERX_DEMO_WRITE") != "YES":
        parser.error("Refusing to write: set AETHERX_DEMO_WRITE=YES explicitly")
    with SessionLocal.begin() as db:
        manifest = seed_showcase(db)
    out_dir = Path(__file__).parent / "demo_output"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "showcase_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("Created/verified fictional showcase fixtures. No existing business records cleared.")
    print("Manifest:", path)
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
