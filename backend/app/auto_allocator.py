"""Explainable background allocator.

Only proposes already-released slots to the waitlist; never cancels or moves a
confirmed appointment or overwrites a competing hold. Concurrency of bookings
still relies on staff-row locks in PostgreSQL.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Appointment, Business, Staff
from .queue_engine import utc
from .waitlist import expire_offers, match_waitlist


def process_business(db: Session, business: Business, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    expired_ids = expire_offers(db, business, now)
    released = db.scalars(select(Appointment).where(
        Appointment.business_id == business.id,
        Appointment.status.in_(("cancelled", "no_show")),
        Appointment.starts_at > now + timedelta(minutes=15),
        Appointment.starts_at < now + timedelta(days=31),
    ).order_by(Appointment.starts_at, Appointment.id).limit(300)).all()
    offered = []
    for appointment in released:
        db.scalar(select(Staff.id).where(Staff.id == appointment.staff_id,
            Staff.business_id == business.id).with_for_update())
        # Recheck the source after obtaining the staff lock.
        db.scalar(select(Appointment.id).where(Appointment.id == appointment.id).with_for_update())
        offer = match_waitlist(db, appointment, business, now=now)
        if offer:
            db.flush()
            offered.append({"offer_id": offer.id, "reference": appointment.reference,
                            "waitlist_entry_id": offer.waitlist_entry_id})
    return {"business_id": business.id, "expired_offers": len(expired_ids),
            "created_offers": len(offered), "offers": offered,
            "strategy": "FIFO by join time, same active service and staff, conflict-checked; acceptance required"}


def process_all(db: Session) -> list[dict]:
    results=[]
    for business in db.scalars(select(Business).where(Business.active.is_(True),
                                                     Business.is_demo.is_(True))).all():
        results.append(process_business(db,business))
    db.commit()
    return results
