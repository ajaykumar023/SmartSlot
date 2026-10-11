"""Populate reproducible FICTIONAL Member 4 demo cases, no external integrations.

Run AFTER migrations and `python seed.py`:
    python seed_scenarios.py

Generates example booking passes in ignored demo_output/ for local presentations.
Never publish them or include them in source control.
"""
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
import secrets, string
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Appointment, Business, CustomerArrival, Service, SlotOffer, Staff, StaffPresence, WaitlistEntry
from app.scheduling import candidate_slots
from app.qr import create_pass, token_hash
from app.waitlist import match_waitlist
from app.queue_engine import utc


def reference():
    return 'SS-' + ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def seed_scenarios():
    output_dir = Path(__file__).parent / 'demo_output'
    output_dir.mkdir(exist_ok=True)
    report = []
    passes = []
    with SessionLocal.begin() as db:
        business = db.scalar(select(Business).where(Business.demo_key == 'clinic', Business.is_demo.is_(True)))
        if business is None:
            raise RuntimeError('First run: alembic upgrade head; python seed.py')
        service = db.scalar(select(Service).where(Service.business_id == business.id, Service.name == 'General consultation'))
        person = db.scalar(select(Staff).where(Staff.business_id == business.id, Staff.name == 'Dr. Anika Rao'))
        if not service or not person:
            raise RuntimeError('Clinic services/staff not seeded. Run python seed.py')
        report += [f'BUSINESS_ID={business.id}', f'SERVICE_ID={service.id}', f'STAFF_ID={person.id}']
        existing = db.scalar(select(Appointment.id).where(Appointment.business_id == business.id,
            Appointment.customer_email == 'demo.booking@aetherx.example'))
        if existing:
            print('Scenarios already seeded. To demonstrate newly generated QR codes, use a fresh local database.')
            return
        tz = ZoneInfo(business.timezone)
        tomorrow = datetime.now(tz).date() + timedelta(days=2)
        # Pick the first available weekday within the coming two weeks.
        chosen_date, slot_list = None, []
        for offset in range(14):
            day = tomorrow + timedelta(days=offset)
            slots = [x for x in candidate_slots(db,business,service.id,day,day,person.id)
                if 10 <= datetime.fromisoformat(x['starts_at']).astimezone(tz).hour <= 14]
            if slots:
                chosen_date, slot_list = day, slots
                break
        if chosen_date is None:
            raise RuntimeError('No available clinic appointments in next 2 weeks; inspect staff availability')
        # Keep enough space between seeded appointments (service length plus buffers).
        times = [slot_list[0]]
        for slot in slot_list[1:]:
            if utc(datetime.fromisoformat(slot['starts_at'])) >= utc(datetime.fromisoformat(times[-1]['ends_at'])) + timedelta(minutes=15):
                times.append(slot)
            if len(times) == 3: break
        if len(times) < 3:
            raise RuntimeError('Not enough free time to create 3 demonstration bookings')
        examples = [
            ('Demo Booking', 'demo.booking@aetherx.example', 'confirmed'),
            ('Demo Delayed Arrival', 'demo.late@aetherx.example', 'confirmed'),
            ('Demo Cancelled Slot', 'demo.cancelled@aetherx.example', 'cancelled'),
        ]
        rows = []
        for (name, email, target_status), slot in zip(examples,times):
            token, image = create_pass()
            row = Appointment(business_id=business.id,service_id=service.id,staff_id=person.id,
                customer_name=name,customer_email=email,reference=reference(),qr_token_hash=token_hash(token),
                starts_at=datetime.fromisoformat(slot['starts_at']),ends_at=datetime.fromisoformat(slot['ends_at']),
                duration_minutes=service.duration_minutes,
                buffer_minutes=business.default_buffer_minutes+service.buffer_minutes,status='confirmed')
            db.add(row); db.flush()
            rows.append((row, target_status))
            passes.append((row.reference, name, image))
            report += [f'{name}: {row.reference} at {utc(row.starts_at).astimezone(tz).isoformat()}']
        db.add(CustomerArrival(appointment_id=rows[1][0].id,status='on_the_way',eta_minutes=40,
            updated_at=datetime.now(timezone.utc)))
        for name,email,minutes_ago in [
            ('Demo Waitlist First','demo.wait1@aetherx.example',10),
            ('Demo Waitlist Second','demo.wait2@aetherx.example',5),
        ]:
            db.add(WaitlistEntry(business_id=business.id,service_id=service.id, customer_email=email,
                customer_name=name,preferred_date=chosen_date.isoformat(),status='waiting',
                created_at=datetime.now(timezone.utc)-timedelta(minutes=minutes_ago)))
        db.flush()
        released = rows[2][0]
        released.status = 'cancelled'
        db.flush()
        offer = match_waitlist(db, released, business)
        if offer:
            db.flush()
            report += [f'Waitlist offer created: id={offer.id}, 20-minute expiry (first eligible customer)',
                'Waitlist login: demo.wait1@aetherx.example; accept and receive new QR pass.',
                'Second waitlisted user: demo.wait2@aetherx.example']
        else:
            report += ['No waitlist offer: another conflict or insufficient advance notice; inspect scenario']
        presence = db.scalar(select(StaffPresence).where(StaffPresence.business_id == business.id,
            StaffPresence.staff_id == person.id))
        if not presence:
            db.add(StaffPresence(business_id=business.id, staff_id=person.id, status='on_site',
                source='admin_demo', updated_at=datetime.now(timezone.utc)))
    html = ["<!doctype html><meta charset='utf-8'><title>SmartSlot Demo QR Passes - PRIVATE</title>",
        "<style>body{font:16px system-ui;margin:3rem;background:#f8fafc}article{display:inline-block;background:white;border:1px solid #ddd;border-radius:12px;margin:12px;padding:20px}img{width:220px}small{display:block}</style>",
        '<h1>SmartSlot — Local demo QR passes</h1><p>FICTIONAL accounts only. Do not publish these QR tokens.</p>']
    for ref,name,image in passes:
        html.append(f'<article><h3>{escape(name)}</h3><p>{escape(ref)}</p><img alt="QR pass" src="{image}"><small>Only valid during the check-in window for active bookings.</small></article>')
    (output_dir/'demo_passes.html').write_text('\n'.join(html),encoding='utf-8')
    (output_dir/'demo_notes.txt').write_text('\n'.join(report),encoding='utf-8')
    print('\n'.join(report))
    print('Private QR cards: backend/demo_output/demo_passes.html')


if __name__=='__main__':
    seed_scenarios()
