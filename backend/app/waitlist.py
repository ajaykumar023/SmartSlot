"""Member 4: FIFO matching and offer expiry/re-offer lifecycle."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Appointment, Notification, AdminAlert, Service, SlotOffer, Staff, WaitlistEntry
from .scheduling import candidate_slots
from .queue_engine import utc


def notify(db: Session, business_id: int, email: str, message: str):
    db.add(Notification(business_id=business_id, customer_email=email.lower(), message=message, simulated=True))


def offer_recipient(db: Session, offer: SlotOffer) -> str:
    """A waitlist offer belongs to the waitlisted customer, NOT the cancelled customer."""
    if offer.waitlist_entry_id:
        entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
        return entry.customer_email if entry else ""
    source = db.get(Appointment, offer.appointment_id)
    return source.customer_email if source else ""


def match_waitlist(db: Session, appointment: Appointment, business, now: datetime | None = None):
    now = utc(now or datetime.now(timezone.utc))
    if appointment.status not in ("cancelled", "no_show") or utc(appointment.starts_at) < now + timedelta(minutes=15):
        return None  # Cannot notify someone about a slot too soon or in the past.
    other = db.scalar(select(SlotOffer).where(SlotOffer.appointment_id == appointment.id,
        SlotOffer.kind == "waitlist", SlotOffer.status == "pending", SlotOffer.expires_at > now))
    if other:
        return None  # One exclusive temporary hold at a time.
    local_date = utc(appointment.starts_at).astimezone(ZoneInfo(business.timezone)).date()
    entries = db.scalars(select(WaitlistEntry).where(
        WaitlistEntry.business_id == appointment.business_id, WaitlistEntry.service_id == appointment.service_id,
        WaitlistEntry.status == "waiting", WaitlistEntry.preferred_date == local_date.isoformat()
    ).order_by(WaitlistEntry.created_at, WaitlistEntry.id)).all()
    # Do not repeatedly offer the same released appointment to someone who already declined or timed out.
    prior = set(db.scalars(select(SlotOffer.waitlist_entry_id).where(
        SlotOffer.appointment_id == appointment.id, SlotOffer.kind == "waitlist")).all())
    for entry in entries:
        if entry.id in prior:
            continue
        feasible = candidate_slots(db, business, entry.service_id, local_date, local_date, appointment.staff_id)
        match = next((slot for slot in feasible if utc(datetime.fromisoformat(slot["starts_at"])) == utc(appointment.starts_at)), None)
        if not match:
            continue
        offer = SlotOffer(business_id=appointment.business_id, appointment_id=appointment.id, staff_id=appointment.staff_id,
            waitlist_entry_id=entry.id, starts_at=appointment.starts_at, ends_at=datetime.fromisoformat(match["ends_at"]),
            kind="waitlist", status="pending", expires_at=now + timedelta(minutes=20))
        entry.status = "offered"
        db.add(offer)
        notify(db, appointment.business_id, entry.customer_email, "A matching appointment opened! Accept your SmartSlot offer within 20 minutes.")
        db.add(AdminAlert(business_id=appointment.business_id, kind="waitlist_offer",
            reference=appointment.reference,
            message=f"Smart queue: a released {appointment.reference} slot was offered automatically to the earliest eligible waitlisted customer."))
        return offer
    return None


def expire_offers(db: Session, business, now: datetime | None = None) -> list[int]:
    """Expire all stale offers; offer freed slots to the next eligible waiting customer."""
    now = utc(now or datetime.now(timezone.utc))
    pending = db.scalars(select(SlotOffer).where(SlotOffer.business_id == business.id,
        SlotOffer.status == "pending", SlotOffer.expires_at <= now).order_by(SlotOffer.id).with_for_update()).all()
    released = []
    for offer in pending:
        offer.status, offer.responded_at = "expired", now
        if offer.kind == "waitlist":
            entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
            if entry and entry.status == "offered":
                entry.status = "waiting"
            released.append(offer.appointment_id)
    db.flush()
    source_rows = [db.get(Appointment, appointment_id) for appointment_id in sorted(set(released))]
    for staff_id in sorted({r.staff_id for r in source_rows if r is not None}):
        db.scalar(select(Staff.id).where(Staff.id == staff_id, Staff.business_id == business.id).with_for_update())
    for source in source_rows:
        appointment_id = source.id if source else None
        if source:
            # Admin/booking flows acquire the staff row lock; this is also serialized by the source row.
            db.scalar(select(Appointment.id).where(Appointment.id == appointment_id).with_for_update())
            match_waitlist(db, source, business, now=now)
    return [offer.id for offer in pending]
