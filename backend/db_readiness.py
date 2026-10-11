"""READ ONLY database health review; no table writes or migrations.

Run from backend/: python db_readiness.py
"""
from collections import Counter
from sqlalchemy import select
from app.database import SessionLocal, engine
from app.models import Business, Appointment, Staff, StaffService, StaffAbsence
from app.queue_engine import ACTIVE, overlaps


def report(db):
    branches = list(db.scalars(select(Business).where(Business.is_demo.is_(True))).all())
    staff = list(db.scalars(select(Staff)).all())
    linked = {sid for sid in db.scalars(select(StaffService.staff_id)).all()}
    active = list(db.scalars(select(Appointment).where(Appointment.status.in_(ACTIVE))).all())
    by_staff = {}
    for booking in active:
        by_staff.setdefault(booking.staff_id, []).append(booking)
    collisions = []
    for staff_id, rows in by_staff.items():
        ordered = sorted(rows, key=lambda a: a.starts_at)
        for i, current in enumerate(ordered):
            for later in ordered[i + 1:]:
                if overlaps(current.starts_at, current.ends_at, current.buffer_minutes,
                            later.starts_at, later.ends_at, later.buffer_minutes):
                    collisions.append({'staff_id': staff_id,
                        'reference_a': current.reference, 'reference_b': later.reference})
    return {'database_driver': engine.dialect.name,
            'demo_branch_count': len(branches), 'total_employee_rows_all_businesses': len(staff),
            'bookable_employee_rows_all_businesses': sum(s.id in linked for s in staff),
            'active_appointments_all_businesses': len(active),
            'overlap_pair_count': len(collisions),
            'overlap_examples': collisions[:15],
            'note': 'Read only. Does not lock rows or certify concurrent booking safety.'}


if __name__ == '__main__':
    import json
    with SessionLocal() as session:
        print(json.dumps(report(session), indent=2))
