"""AETHERX multi-industry fictional workforce + booking data. No schema changes.

PREVIEW (no database connection): python demo_finalize_seed.py
APPLY (on a backed-up development DB only):
    $env:AETHERX_DEMO_WRITE='YES'
    python demo_finalize_seed.py --apply
    Remove-Item Env:AETHERX_DEMO_WRITE

Requires migrations through 0008 and the showcase demo business rows. All
records use demo-only business IDs; no existing bookings are overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import (
    Appointment, Availability, BookingServiceIntake, Business, BusinessHours,
    Organization, Service, Staff, StaffAbsence, StaffService, WaitlistEntry,
)
from app.qr import token_hash
from demo_identity_names import employee_name, fictional_customer_name
from app.queue_engine import ACTIVE, overlaps, is_staff_working, utc

ORG_SLUG = 'aetherx-showcase-v1'
TZ = ZoneInfo('Asia/Kolkata')
# Headcounts include the fictional professionals created by demo_showcase_seed.py.
# Nurses, receptionists, coordinators etc are intentionally not bound to services.
PLAN = {
    'showcase_salon_a': {'target': 14, 'professional_title': 'Stylist', 'professional_total': 9,
        'helpers': [('Receptionist', 2), ('Salon assistant', 2), ('Salon manager', 1)]},
    'showcase_salon_b': {'target': 12, 'professional_title': 'Stylist', 'professional_total': 8,
        'helpers': [('Receptionist', 2), ('Salon assistant', 1), ('Salon manager', 1)]},
    'showcase_clinic': {'target': 14, 'professional_title': 'Clinician', 'professional_total': 7,
        'helpers': [('Nurse', 3), ('Receptionist', 2), ('Clinic coordinator', 1), ('Clinic manager', 1)]},
    'showcase_repair': {'target': 12, 'professional_title': 'Technician', 'professional_total': 8,
        'helpers': [('Front desk', 2), ('Service supervisor', 1), ('Inventory assistant', 1)]},
    'showcase_consult': {'target': 8, 'professional_title': 'Consultant', 'professional_total': 5,
        'helpers': [('Scheduling coordinator', 2), ('Office manager', 1)]},
}
PROFESSIONAL_SEED_NAMES = {
    'showcase_salon_a': ('Demo Stylist A', 'Demo Stylist B'),
    'showcase_salon_b': ('Demo Backup Stylist',),
    'showcase_clinic': ('Demo Clinician',),
    'showcase_repair': ('Demo Technician',),
    'showcase_consult': ('Demo Consultant',),
}
CATEGORY_INTAKE = {
    'salon': ('Style consultation', {'desired_style': 'Trim and maintain shape'}),
    'clinic': ('Fictional routine booking', {'visit_type': 'Follow-up', 'visit_reason': 'Routine appointment'}),
    'repair_center': ('Device inspection', {'item_type': 'Laptop', 'reported_issue': 'Intermittent issue'}),
    'consultant': ('Project planning', {'consultation_goal': 'Review project milestones'}),
}


def _get_showcase(db: Session) -> dict[str, Business]:
    org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
    if not org:
        raise ValueError('Showcase organization missing; run demo_showcase_seed.py --apply first.')
    rows = list(db.scalars(select(Business).where(Business.demo_key.in_(tuple(PLAN)))))
    result = {b.demo_key: b for b in rows}
    if set(result) != set(PLAN):
        raise ValueError('Missing showcase business; run demo_showcase_seed.py --apply first.')
    if any(not b.is_demo or not b.active or b.organization_id != org.id for b in result.values()):
        raise ValueError('Refusing changes: a target business is not an active showcase branch')
    return result


def _ensure_person(db: Session, business: Business, name: str, title: str, service: Service | None) -> Staff:
    display_name = employee_name(business.demo_key, name)
    matches = list(db.scalars(select(Staff).where(
        Staff.business_id == business.id, Staff.name.in_((name, display_name)))))
    if len(matches) > 1:
        raise ValueError(f'Duplicate demo staff identities for {name}; inspect rows manually')
    staff = matches[0] if matches else None
    if not staff:
        staff = Staff(business_id=business.id, name=display_name, title=title, active=True)
        db.add(staff)
        db.flush()
    elif staff.name != display_name:
        staff.name = display_name
    if service:
        if staff.active and not db.get(StaffService, (staff.id, service.id)):
            # Only generated professionals are qualified for this explicit demo service.
            db.add(StaffService(staff_id=staff.id, service_id=service.id))
        for weekday in range(7):
            existing = db.scalar(select(Availability).where(
                Availability.staff_id == staff.id, Availability.business_id == business.id,
                Availability.weekday == weekday))
            if not existing:
                db.add(Availability(business_id=business.id, staff_id=staff.id,
                    weekday=weekday, start_time=time(9, 0), end_time=time(19, 0)))
    return staff


def _safe_slot(db: Session, business: Business, service: Service, staff: Staff,
               start: datetime) -> bool:
    end = start + timedelta(minutes=service.duration_minutes)
    fake = type('AppointmentStub', (), {'staff_id': staff.id, 'service_id': service.id})()
    if not is_staff_working(db, business, fake, start, end):
        return False
    total_buffer = business.default_buffer_minutes + service.buffer_minutes
    active = list(db.scalars(select(Appointment).where(
        Appointment.staff_id == staff.id, Appointment.status.in_(ACTIVE))))
    if any(overlaps(start, end, total_buffer, old.starts_at, old.ends_at, old.buffer_minutes)
           for old in active):
        return False
    absences = list(db.scalars(select(StaffAbsence).where(
        StaffAbsence.staff_id == staff.id, StaffAbsence.business_id == business.id)))
    if any(utc(a.starts_at) < end + timedelta(minutes=total_buffer) and
           utc(a.ends_at) > start for a in absences):
        return False
    return True


def _ensure_workforce(db: Session, businesses: dict[str, Business]) -> dict[str, list[Staff]]:
    newly_added_professionals = {}
    for key, plan in PLAN.items():
        business = businesses[key]
        service = db.scalar(select(Service).where(
            Service.business_id == business.id, Service.active.is_(True)).order_by(Service.id))
        if not service:
            raise ValueError(f'No active demo service in {key}')
        base_names = PROFESSIONAL_SEED_NAMES[key]
        add_professionals = plan['professional_total'] - len(base_names)
        people = []
        for number in range(1, add_professionals + 1):
            name = f'Demo {key.replace("showcase_", "").replace("_", " ").title()} {plan["professional_title"]} {number:02d}'
            people.append(_ensure_person(db, business, name, plan['professional_title'], service))
        for helper_title, count in plan['helpers']:
            for number in range(1, count + 1):
                name = f'Demo {key.replace("showcase_", "").replace("_", " ").title()} {helper_title} {number:02d}'
                _ensure_person(db, business, name, helper_title, None)
        newly_added_professionals[key] = people
        # Preserve existing customers, staff states and base demo professional rows.
        # Check our expected rows exist, but do not delete any extra manually added staff.
        expected = len(base_names) + add_professionals + sum(c for _, c in plan['helpers'])
        if expected != plan['target']:
            raise AssertionError(f'Invalid staffing plan: {key}')
    db.flush()
    return newly_added_professionals


def _preserve_reroute_demo(db: Session, businesses: dict[str, Business], newcomers: dict[str, list[Staff]]) -> int:
    """Block newly generated Salon A stylists only around the existing route scenario.

    Otherwise adding staff would silently invalidate our 'no local staff' demo.
    Avoid applying an absence if the reroute scenario has already been transferred.
    """
    target = db.scalar(select(Appointment).where(
        Appointment.reference == 'SS-DM-ROUTE',
        Appointment.customer_email == 'demo.route@aetherx.example'))
    if not target or target.business_id != businesses['showcase_salon_a'].id:
        return 0
    start = utc(target.starts_at) - timedelta(minutes=5)
    end = utc(target.starts_at) + timedelta(minutes=70)
    created = 0
    for staff in newcomers['showcase_salon_a']:
        old = db.scalar(select(StaffAbsence).where(
            StaffAbsence.business_id == target.business_id,
            StaffAbsence.staff_id == staff.id,
            StaffAbsence.source == 'workforce_route_demo'))
        if old:
            continue  # Never reset an operator-modified absence.
        db.add(StaffAbsence(business_id=target.business_id, staff_id=staff.id,
            starts_at=start, ends_at=end, reason='break', source='workforce_route_demo'))
        created += 1
    return created


def _next_days(anchor: datetime) -> list:
    """Weekdays+Saturday over a 3-week booking window, no Sundays."""
    base = anchor.astimezone(TZ).date()
    days = []
    for offset in range(-5, 22):
        day = base + timedelta(days=offset)
        if day.weekday() != 6:
            days.append(day)
    return days


def seed_final_demo(db: Session, now_utc: datetime | None = None, booking_count: int = 150) -> dict:
    """Insert 60-total-staff showcase plus booking fixture rows, idempotently.

    Caller controls transaction. Does NOT call TomTom, change real bookings,
    create login accounts or alter service qualifications on existing staff.
    """
    if booking_count < 0 or booking_count > 300:
        raise ValueError('booking_count must be between 0 and 300')
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        raise ValueError('now_utc must include a timezone')
    businesses = _get_showcase(db)
    professionals = _ensure_workforce(db, businesses)
    absences_created = _preserve_reroute_demo(db, businesses, professionals)
    days = _next_days(now_utc)
    keys = list(PLAN)
    results = []
    # Distinct fictional customer IDs cycle through 100 names, while 150
    # bookings demonstrate repeat business and booking history.
    for index in range(booking_count):
        reference = f'SS-WF-{index + 1:04d}'
        email = f'showcase.customer{index % 100 + 1:03d}@aetherx.example'
        previous = list(db.scalars(select(Appointment).where(Appointment.reference == reference)))
        if previous:
            if len(previous) != 1 or previous[0].customer_email != email:
                raise ValueError(f'Demo reference collision: {reference}')
            old_business = db.get(Business, previous[0].business_id)
            if not old_business or not old_business.is_demo or old_business.demo_key not in PLAN:
                raise ValueError(f'Reference collision with non-showcase record: {reference}')
            booking = previous[0]  # Preserve cancellations, transfers and edits.
        else:
            key = keys[index % len(keys)]
            business = businesses[key]
            service = db.scalar(select(Service).where(
                Service.business_id == business.id, Service.active.is_(True)).order_by(Service.id))
            if not service:
                raise ValueError(f'Missing active service in {key}')
            people = [s for s in professionals[key] if s.active]
            if not people:
                raise ValueError(f'No active added demo professionals for {key}')
            chosen = None
            for offset in range(len(days)):
                day = days[(index // len(keys) + offset) % len(days)]
                # Preserve intended completed vs future bookings without falsifying
                # attendance for near-future dates.
                is_past = day < now_utc.astimezone(TZ).date()
                for hour in (10, 11, 12, 14, 15, 16, 17):
                    begin = datetime.combine(day, time(hour, (index % 2) * 30), TZ).astimezone(timezone.utc)
                    if not is_past and begin <= now_utc + timedelta(hours=2):
                        continue
                    for staff in people:
                        if _safe_slot(db, business, service, staff, begin):
                            chosen = (staff, begin, is_past)
                            break
                    if chosen:
                        break
                if chosen:
                    break
            if not chosen:
                raise ValueError(f'No safe employee slot for {reference}; rolling back all changes')
            staff, start, in_past = chosen
            status = 'completed' if in_past else ('cancelled' if index % 13 == 0 else 'confirmed')
            booking = Appointment(business_id=business.id, service_id=service.id, staff_id=staff.id,
                customer_email=email, customer_name=fictional_customer_name(index % 100 + 1),
                reference=reference, qr_token_hash=token_hash(secrets.token_urlsafe(32)),
                starts_at=start, ends_at=start + timedelta(minutes=service.duration_minutes),
                duration_minutes=service.duration_minutes, buffer_minutes=service.buffer_minutes,
                status=status)
            db.add(booking)
            db.flush()
            if business.category in CATEGORY_INTAKE:
                summary, answers = CATEGORY_INTAKE[business.category]
                db.add(BookingServiceIntake(appointment_id=booking.id, category=business.category,
                    summary=summary, notes='Fictional demo service description only.', answers=dict(answers)))
        results.append({'reference': booking.reference, 'name': booking.customer_name,
                        'email': booking.customer_email, 'business_id': booking.business_id,
                        'staff_id': booking.staff_id, 'status': booking.status,
                        'starts_at': utc(booking.starts_at).isoformat()})
    db.flush()
    headcount = {}
    for key, business in businesses.items():
        rows = db.scalars(select(Staff).where(Staff.business_id == business.id)).all()
        professionals_count = sum(bool(db.scalar(select(StaffService.staff_id).where(
            StaffService.staff_id == row.id))) for row in rows)
        headcount[key] = {'employees_total': len(rows), 'qualified_professionals': professionals_count,
                          'support_staff': len(rows) - professionals_count, 'business_id': business.id}
    return {'generated_at': now_utc.isoformat(), 'fictional': True,
            'businesses': headcount, 'newly_seeded_bookings_or_existing': len(results),
            'distinct_customer_emails': len({x['email'] for x in results}),
            'reroute_demo_absences_created': absences_created,
            'appointments': results,
            'notes': 'Synthetic data; staff in this table are not authenticated employee accounts.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Perform the seed on a backed-up dev PostgreSQL database')
    parser.add_argument('--bookings', type=int, default=150, help='Number of fictional booking rows, max 300')
    args = parser.parse_args()
    if not args.apply:
        print('PREVIEW ONLY. Zero database changes or connections.')
        print('Showcase staff targets:')
        for key, plan in PLAN.items():
            print(f'  {key}: {plan["target"]} total; {plan["professional_total"]} professionals + '
                  f'{sum(n for _, n in plan["helpers"])} support workers')
        print(f'Synthetic new bookings: {args.bookings}; unique customer identities up to 100.')
        print('Will preserve the original demo reroute scenario by adding artificial staff breaks.')
        print('REQUIRES demo_showcase_seed.py --apply to have succeeded previously.')
        return
    if os.environ.get('AETHERX_DEMO_WRITE') != 'YES':
        parser.error('Refusing to modify database unless AETHERX_DEMO_WRITE=YES is set')
    if engine.dialect.name != 'postgresql':
        parser.error('Apply only to backed-up dev PostgreSQL; SQLite allowed in unit tests only')
    with SessionLocal.begin() as db:
        data = seed_final_demo(db, booking_count=args.bookings)
    out = Path(__file__).parent / 'demo_output'
    out.mkdir(exist_ok=True)
    destination = out / 'final_backend_manifest.json'
    destination.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('Committed fictional staff and appointments to PostgreSQL.')
    for key, size in data['businesses'].items():
        print(f'  {key}: {size["employees_total"]} workers ({size["qualified_professionals"]} bookable, '
              f'{size["support_staff"]} helpers)')
    print('Manifest:', destination)

if __name__ == '__main__':
    main()
