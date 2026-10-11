"""Creates two clashing fictional reservations concurrently and cleans BOTH up.

Only run on a backed-up DEVELOPMENT PostgreSQL database after Alembic upgrade.
Tests whether the DB constraint, not Python timing, rejects an overlap.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal, engine
from app.models import Appointment, StaffService, Staff, Service, Business

if engine.dialect.name != 'postgresql':
    raise SystemExit('This concurrency verifier requires PostgreSQL')

nonce = uuid4().hex.upper()
refs = ['SS-' + nonce[i:i+6] for i in (0,6)]
if refs[0] == refs[1]:
    raise SystemExit('Unexpected test reference collision')

with SessionLocal() as db:
    mapping = db.scalar(select(StaffService).join(Staff, Staff.id == StaffService.staff_id)
                        .join(Service, Service.id == StaffService.service_id)
                        .join(Business, Business.id == Staff.business_id)
                        .where(Staff.active.is_(True), Service.active.is_(True), Business.active.is_(True)).limit(1))
    if not mapping:
        raise SystemExit('Seed at least one active professional with a service before running this test')
    staff_id = mapping.staff_id
    service_id = mapping.service_id
    staff = db.get(Staff, staff_id)
    business_id = staff.business_id
    service = db.get(Service, service_id)
    buffer_minutes = service.buffer_minutes
    duration = service.duration_minutes
    starts = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=750)
    ends = starts + timedelta(minutes=duration)

barrier = Barrier(2)
def attempt(index):
    with SessionLocal() as db:
        row=Appointment(business_id=business_id, staff_id=staff_id, service_id=service_id,
                        customer_name='AETHERX Test Only', customer_email='aetherx-test@example.invalid',
                        reference=refs[index], qr_token_hash=uuid4().hex + uuid4().hex,
                        starts_at=starts, ends_at=ends, duration_minutes=duration,
                        buffer_minutes=buffer_minutes, status='confirmed')
        db.add(row)
        barrier.wait(timeout=10)
        try:
            db.commit()
            return 'committed'
        except IntegrityError as exc:
            db.rollback()
            if getattr(exc.orig, 'sqlstate', '') == '23P01':
                return 'conflict_rejected'
            return f'unexpected_integrity_error_{getattr(exc.orig, "sqlstate", "unknown")}'
        except Exception as exc:
            db.rollback()
            return f'unexpected_{type(exc).__name__}'

results=[]
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(attempt, i) for i in range(2)]
        results=[f.result(timeout=30) for f in tasks]
finally:
    with SessionLocal.begin() as db:
        db.execute(delete(Appointment).where(Appointment.reference.in_(refs),
                                             Appointment.customer_email=='aetherx-test@example.invalid'))
print('Concurrent transaction outcomes:', sorted(results))
if sorted(results) != ['committed', 'conflict_rejected']:
    raise SystemExit('FAIL: PostgreSQL booking conflict prevention was not verified')
print('PASS: Exactly one booking committed; the competing booking was rejected. Test rows cleaned up.')
