"""Fictional customer bookings and waitlist data for AETHERX showcase branches.

Requires `demo_showcase_seed.py --apply` to have been run first.

Run from backend/: 
  python demo_customers_seed.py            # preview only; zero database writes
  $env:AETHERX_DEMO_WRITE='YES'
  python demo_customers_seed.py --apply    # inserts demo-only fixtures
  Remove-Item Env:AETHERX_DEMO_WRITE

No real accounts are created; this project's demo customer identity is the email
on a booking or waitlist entry. Existing bookings are never reset or modified.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Appointment, Availability, BookingServiceIntake, Business, BusinessHours,
    Organization, Service, Staff, StaffAbsence, StaffService, WaitlistEntry,
)
from app.qr import token_hash

ORG_SLUG = "aetherx-showcase-v1"
LOCAL_TZ = ZoneInfo("Asia/Kolkata")
ACTIVE_STATUSES = ("confirmed", "checked_in", "at_risk")


@dataclass(frozen=True)
class DemoCustomer:
    reference: str
    name: str
    email: str
    business_key: str
    hour: int
    minute: int = 0
    day_offset: int = 0  # From tomorrow; all dates calculated from the seed run date
    status: str = "confirmed"
    summary: str = ""
    notes: str = ""
    answers: dict | None = None


# Fictional names and reserved .example domains. Only demo bookings; no real identities.
CUSTOMERS = (
    DemoCustomer("SS-CU-0001", "Asha Khanna", "demo.asha@aetherx.example", "showcase_salon_a", 10,
                 summary="Classic trim", answers={"desired_style": "Trim", "preferred_length": "medium"}),
    DemoCustomer("SS-CU-0002", "Kabir Mehta", "demo.kabir@aetherx.example", "showcase_salon_a", 11,
                 summary="Low taper fade", notes="Please keep the top longer", answers={"desired_style": "Fade", "preferred_length": "short"}),
    DemoCustomer("SS-CU-0003", "Neha Rao", "demo.neha@aetherx.example", "showcase_salon_a", 12,
                 summary="Layered hairstyle", answers={"desired_style": "Layers", "preferred_length": "long"}),
    DemoCustomer("SS-CU-0004", "Arjun Das", "demo.arjun@aetherx.example", "showcase_salon_a", 14,
                 summary="Simple trim", answers={"desired_style": "Regular cut", "preferred_length": "short"}),
    DemoCustomer("SS-CU-0005", "Mira Shah", "demo.mira@aetherx.example", "showcase_salon_b", 10, 30,
                 summary="Haircut consultation", answers={"desired_style": "Not decided", "preferred_length": "medium"}),
    DemoCustomer("SS-CU-0006", "Jay Patel", "demo.jay@aetherx.example", "showcase_salon_b", 12, 30,
                 summary="Short haircut", answers={"desired_style": "Crew cut", "preferred_length": "short"}),
    DemoCustomer("SS-CU-0007", "Ira Menon", "demo.ira@aetherx.example", "showcase_clinic", 10,
                 summary="Routine consultation", notes="Fictional booking, no health information", answers={"visit_reason": "Routine visit", "visit_type": "First visit"}),
    DemoCustomer("SS-CU-0008", "Dev Nair", "demo.dev@aetherx.example", "showcase_clinic", 11,
                 summary="Follow-up visit", answers={"visit_reason": "Follow-up", "visit_type": "Follow-up"}),
    DemoCustomer("SS-CU-0009", "Tanya Iyer", "demo.tanya@aetherx.example", "showcase_clinic", 12,
                 status="cancelled", summary="Cancelled consultation", answers={"visit_reason": "Routine visit", "visit_type": "First visit"}),
    DemoCustomer("SS-CU-0010", "Sana Roy", "demo.sana@aetherx.example", "showcase_repair", 10,
                 summary="Laptop screen flickers", answers={"item_type": "Laptop", "reported_issue": "Display flickering"}),
    DemoCustomer("SS-CU-0011", "Reyansh Kapoor", "demo.reyansh@aetherx.example", "showcase_repair", 11,
                 summary="Phone charging inspection", answers={"item_type": "Phone", "reported_issue": "Intermittent charging"}),
    DemoCustomer("SS-CU-0012", "Riya Bansal", "demo.riya@aetherx.example", "showcase_repair", 12,
                 summary="Laptop battery assessment", answers={"item_type": "Laptop", "reported_issue": "Low battery life"}),
    DemoCustomer("SS-CU-0013", "Veda Jain", "demo.veda@aetherx.example", "showcase_consult", 10,
                 summary="Prototype review", answers={"consultation_goal": "Product feedback", "project_context": "Prototype"}),
    DemoCustomer("SS-CU-0014", "Farhan Ali", "demo.farhan@aetherx.example", "showcase_consult", 11,
                 summary="Project planning", answers={"consultation_goal": "Milestones", "project_context": "New project"}),
    DemoCustomer("SS-CU-0015", "Diya Bose", "demo.diya@aetherx.example", "showcase_consult", 14,
                 summary="Technical consultation", answers={"consultation_goal": "Technical advice", "project_context": "MVP"}),
)

WAITLIST_CUSTOMERS = (
    ("Demo Reema", "demo.reema@aetherx.example", "showcase_salon_a"),
    ("Demo Nikhil", "demo.nikhil@aetherx.example", "showcase_salon_b"),
    ("Demo Tara", "demo.tara@aetherx.example", "showcase_repair"),
)


def utc(value: datetime) -> datetime:
    """Postgres stores aware timestamps; SQLite tests may return naive UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def next_day(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must have a timezone")
    tomorrow = now_utc.astimezone(LOCAL_TZ).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(0, 0), LOCAL_TZ)


def _has_overlap(db: Session, staff: Staff, start: datetime, end: datetime) -> bool:
    appointments = db.scalars(select(Appointment).where(
        Appointment.staff_id == staff.id,
        Appointment.status.in_(ACTIVE_STATUSES),
    )).all()
    for row in appointments:
        existing_end = utc(row.ends_at) + timedelta(minutes=row.buffer_minutes or 0)
        if utc(row.starts_at) < end and existing_end > start:
            return True
    absences = db.scalars(select(StaffAbsence).where(StaffAbsence.staff_id == staff.id)).all()
    return any(utc(a.starts_at) < end and utc(a.ends_at) > start for a in absences)


def _available(db: Session, business: Business, staff: Staff, start: datetime, end: datetime) -> bool:
    local_start, local_end = start.astimezone(LOCAL_TZ), end.astimezone(LOCAL_TZ)
    if local_start.date() != local_end.date():
        return False
    weekday = local_start.weekday()
    branch_hours = db.scalar(select(BusinessHours).where(
        BusinessHours.business_id == business.id, BusinessHours.weekday == weekday))
    shift = db.scalar(select(Availability).where(
        Availability.business_id == business.id, Availability.staff_id == staff.id,
        Availability.weekday == weekday))
    if not branch_hours or not shift:
        return False
    return (branch_hours.opens_at <= local_start.time() and local_end.time() <= branch_hours.closes_at
            and shift.start_time <= local_start.time() and local_end.time() <= shift.end_time
            and not _has_overlap(db, staff, start, end))


def seed_customers(db: Session, now_utc: datetime | None = None) -> dict:
    """Idempotent inserts of fictional bookings, with caller-controlled commit/rollback.

    Needs the original showcase businesses; it does not create accounts or modify
    non-showcase records. Does not fabricate attendance or live GPS measurements.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
    if not org:
        raise ValueError("Showcase organization missing. Run demo_showcase_seed.py --apply first.")
    keys = {row.demo_key: row for row in db.scalars(select(Business).where(
        Business.organization_id == org.id, Business.is_demo.is_(True))).all()}
    required_keys = {c.business_key for c in CUSTOMERS} | {item[2] for item in WAITLIST_CUSTOMERS}
    if not required_keys.issubset(keys):
        raise ValueError("Showcase branches missing. Run demo_showcase_seed.py --apply first.")
    for key in required_keys:
        if not keys[key].active:
            raise ValueError(f"Showcase branch {key} is inactive; refusing to seed")
    base = next_day(now_utc)
    output = {"generated_at": now_utc.isoformat(), "note": "FICTIONAL demo data; no real customers or accounts",
              "database": "PostgreSQL (DATABASE_URL in backend/.env)", "customers": [], "waitlist_customers": []}

    for customer in CUSTOMERS:
        business = keys[customer.business_key]
        # References reserved for this fixture. Reject collisions even if a different
        # customer uses the same reference at a separate branch.
        records = db.scalars(select(Appointment).where(Appointment.reference == customer.reference)).all()
        if len(records) > 1 or (records and records[0].customer_email != customer.email):
            raise ValueError(f"Reserved demo reference in use: {customer.reference}")
        if records:
            row = records[0]
            current_branch = db.get(Business, row.business_id)
            if not current_branch or not current_branch.is_demo or current_branch.organization_id != org.id:
                raise ValueError(f"Existing booking {customer.reference} is outside the showcase")
            # Preserve all edits, moves and cancellations made through the real UI.
        else:
            service = db.scalar(select(Service).where(Service.business_id == business.id,
                                                      Service.active.is_(True)).order_by(Service.id))
            if not service:
                raise ValueError(f"No active service in {business.demo_key}")
            staff_list = db.scalars(select(Staff).join(StaffService, StaffService.staff_id == Staff.id).where(
                StaffService.service_id == service.id, Staff.business_id == business.id,
                Staff.active.is_(True)).order_by(Staff.id)).all()
            if not staff_list:
                raise ValueError(f"No qualified staff in {business.demo_key}")
            start_local = base + timedelta(days=customer.day_offset, hours=customer.hour, minutes=customer.minute)
            duration = timedelta(minutes=service.duration_minutes)
            # For fixture creation only: choose first conflict-free demo slot within
            # a bounded 3-hour window instead of overwriting another appointment.
            chosen = None
            for bump in range(0, 181, 30):
                start_utc = (start_local + timedelta(minutes=bump)).astimezone(timezone.utc)
                end_utc = start_utc + duration
                for staff in staff_list:
                    if _available(db, business, staff, start_utc,
                                  end_utc + timedelta(minutes=service.buffer_minutes)):
                        chosen = (staff, start_utc, end_utc)
                        break
                if chosen:
                    break
            if not chosen:
                raise ValueError(f"No safe demo slot found for {customer.reference}; no changes committed")
            staff, begin, finish = chosen
            row = Appointment(business_id=business.id, service_id=service.id, staff_id=staff.id,
                              customer_email=customer.email, customer_name=customer.name,
                              reference=customer.reference,
                              qr_token_hash=token_hash(secrets.token_urlsafe(32)),
                              starts_at=begin, ends_at=finish,
                              duration_minutes=service.duration_minutes,
                              buffer_minutes=service.buffer_minutes, status=customer.status)
            db.add(row)
            db.flush()
            if customer.summary:
                db.add(BookingServiceIntake(appointment_id=row.id, category=business.category,
                                            summary=customer.summary, notes=customer.notes,
                                            answers=customer.answers or {}))
        output["customers"].append({"name": row.customer_name, "email": row.customer_email,
                                     "business_id": row.business_id, "reference": row.reference,
                                     "starts_at": utc(row.starts_at).isoformat(), "status": row.status})

    for name, email, business_key in WAITLIST_CUSTOMERS:
        business = keys[business_key]
        service = db.scalar(select(Service).where(Service.business_id == business.id,
                                                  Service.active.is_(True)).order_by(Service.id))
        if not service:
            raise ValueError(f"No active service for waitlist in {business_key}")
        entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.customer_email == email,
                        WaitlistEntry.business_id == business.id))
        if not entry:
            entry = WaitlistEntry(business_id=business.id, service_id=service.id,
                                  customer_email=email, customer_name=name,
                                  preferred_date=base.date().isoformat(), status="waiting")
            db.add(entry)
            db.flush()
        output["waitlist_customers"].append({"name": entry.customer_name, "email": entry.customer_email,
                                              "business_id": entry.business_id,
                                              "status": entry.status, "preferred_date": entry.preferred_date})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Insert fiction-only fixtures, requires AETHERX_DEMO_WRITE=YES")
    args = parser.parse_args()
    if not args.apply:
        print("PREVIEW ONLY. Zero database writes.\n")
        print(f"{len(CUSTOMERS)} fictional bookings + {len(WAITLIST_CUSTOMERS)} waitlist-only customers")
        for c in CUSTOMERS:
            print(f"  {c.reference}  {c.name:20} {c.business_key:18} {c.email}")
        print("\nTo write, first seed the showcase businesses and then run with --apply and AETHERX_DEMO_WRITE=YES.")
        return
    if os.environ.get("AETHERX_DEMO_WRITE") != "YES":
        parser.error("Refusing to write: set AETHERX_DEMO_WRITE=YES explicitly")
    with SessionLocal.begin() as db:
        manifest = seed_customers(db)
    output_dir = Path(__file__).parent / "demo_output"
    output_dir.mkdir(exist_ok=True)
    manifest_path = output_dir / "customer_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Stored {len(manifest['customers'])} fictional customer bookings in the configured database.")
    print(f"Stored {len(manifest['waitlist_customers'])} fictional waitlist entries.")
    print("Demo login and booking reference manifest:", manifest_path)
    print("No standalone customers table or persistent password-based accounts were created.")


if __name__ == "__main__":
    main()
