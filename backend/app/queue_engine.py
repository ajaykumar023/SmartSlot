"""Member 4: deterministic, explainable scheduling rules (not a trained ML model)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Appointment, Availability, Business, BusinessHours, SlotOffer, Staff, StaffPresence, StaffService

ACTIVE = ("confirmed", "checked_in", "at_risk")


def utc(dt: datetime) -> datetime:
    """Normalize database datetimes (also supports SQLite used only in unit tests)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def overlaps(start_a, end_a, buffer_a, start_b, end_b, buffer_b) -> bool:
    """Half-open intervals with both appointments' post-service buffers."""
    return utc(start_a) < utc(end_b) + timedelta(minutes=buffer_b) and utc(start_b) < utc(end_a) + timedelta(minutes=buffer_a)


def is_staff_working(db: Session, business: Business, appointment: Appointment, start: datetime, end: datetime) -> bool:
    """Full time-window check; never shift into closed hours or an unqualified staff shift."""
    local_start, local_end = utc(start).astimezone(ZoneInfo(business.timezone)), utc(end).astimezone(ZoneInfo(business.timezone))
    if local_start.date() != local_end.date():
        return False
    hours = db.scalar(select(BusinessHours).where(BusinessHours.business_id == business.id, BusinessHours.weekday == local_start.weekday()))
    shift = db.scalar(select(Availability).where(Availability.business_id == business.id, Availability.staff_id == appointment.staff_id,
        Availability.weekday == local_start.weekday()))
    person = db.get(Staff, appointment.staff_id)
    qualified = db.get(StaffService, (appointment.staff_id, appointment.service_id))
    if not (hours and shift and person and person.active and person.business_id == business.id and qualified):
        return False
    # End exactly at closing is valid; buffer may extend beyond closing if policy permits (original slot policy does).
    return (hours.opens_at <= local_start.time() < hours.closes_at
        and local_end.time() <= hours.closes_at
        and shift.start_time <= local_start.time() < shift.end_time
        and local_end.time() <= shift.end_time)


def available_for_shift(db: Session, business: Business, appointment: Appointment,
                        start: datetime, end: datetime, ignore_offer_id: int | None = None,
                        now: datetime | None = None) -> tuple[bool, str]:
    now = utc(now or datetime.now(timezone.utc))
    start, end = utc(start), utc(end)
    if start < now + timedelta(minutes=5):
        return False, "less than 5 minutes' notice"
    if not is_staff_working(db, business, appointment, start, end):
        return False, "outside qualified staff working hours"
    # Manual demo presence is a short-lived signal, not proof of future attendance.
    presence = db.scalar(select(StaffPresence).where(StaffPresence.business_id == business.id,
        StaffPresence.staff_id == appointment.staff_id))
    if (presence and presence.status != "on_site" and start < now + timedelta(minutes=60)
        and utc(presence.updated_at) >= now - timedelta(minutes=45)):
        return False, "staff currently reported away or on break (unverified manual status)"
    others = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.staff_id == appointment.staff_id, Appointment.id != appointment.id,
        Appointment.status.in_(ACTIVE))).all()
    if any(overlaps(start, end, appointment.buffer_minutes, other.starts_at, other.ends_at, other.buffer_minutes) for other in others):
        return False, "another appointment or buffer occupies this time"
    # Waitlist holds reserve a released appointment until offer expiry.
    holds = db.scalars(select(SlotOffer).where(SlotOffer.business_id == business.id,
        SlotOffer.staff_id == appointment.staff_id, SlotOffer.kind == "waitlist",
        SlotOffer.status == "pending", SlotOffer.expires_at > now)).all()
    if any((ignore_offer_id is None or hold.id != ignore_offer_id)
           and overlaps(start, end, appointment.buffer_minutes, hold.starts_at, hold.ends_at, appointment.buffer_minutes)
           for hold in holds):
        return False, "a waitlist customer has a temporary hold on this slot"
    # Offers to OTHER appointments cannot promise the same proposed start.
    proposed = db.scalars(select(SlotOffer).where(SlotOffer.business_id == business.id,
        SlotOffer.staff_id == appointment.staff_id, SlotOffer.kind.in_(("queue_shift", "delay_shift")),
        SlotOffer.status == "pending", SlotOffer.expires_at > now)).all()
    for hold in proposed:
        if hold.id != ignore_offer_id and hold.appointment_id != appointment.id and overlaps(
                start, end, appointment.buffer_minutes, hold.starts_at, hold.ends_at, appointment.buffer_minutes):
            return False, "another customer has a pending offer on this time"
    return True, "qualified staff is available and the slot has no conflicts"


def shift_recommendations(db: Session, business: Business, appointment: Appointment,
                          now: datetime | None = None) -> list[dict]:
    if appointment.status != "confirmed":
        return []
    if utc(appointment.starts_at) <= utc(now or datetime.now(timezone.utc)):
        return []
    suggestions = []
    for minutes in (15, 30, 45, 60):
        start = utc(appointment.starts_at) - timedelta(minutes=minutes)
        end = utc(appointment.ends_at) - timedelta(minutes=minutes)
        ok, reason = available_for_shift(db, business, appointment, start, end, now=now)
        if ok:
            suggestions.append({"advance_minutes": minutes, "starts_at": start.isoformat(),
                "ends_at": end.isoformat(), "reason": reason})
    return suggestions


# Limited Delay Recovery: offer a *later* start to the owner, without touching other bookings.
def delay_recommendations(db: Session, business: Business, appointment: Appointment,
                          eta_minutes: int, max_delay_minutes: int = 30,
                          now: datetime | None = None) -> list[dict]:
    """Return only later options that the customer can reach and staff can actually fulfill.

    ETA is a customer estimate until a verified routing integration is configured.
    An original slot remains reserved until the customer accepts an offered time.
    """
    now = utc(now or datetime.now(timezone.utc))
    if not (0 <= eta_minutes <= 180 and 5 <= max_delay_minutes <= 30):
        return []
    original = utc(appointment.starts_at)
    if (appointment.status != "confirmed"
            or original + timedelta(minutes=business.queue_grace_minutes) < now
            or original > now + timedelta(hours=3)):
        return []  # Only relevant shortly before the appointment.
    arrival = now + timedelta(minutes=eta_minutes)
    if arrival <= original + timedelta(minutes=business.queue_grace_minutes):
        return []  # Do not delay someone expected within the allowed grace window.
    result = []
    for minutes in (15, 30):
        if minutes > max_delay_minutes:
            continue
        start = utc(appointment.starts_at) + timedelta(minutes=minutes)
        end = utc(appointment.ends_at) + timedelta(minutes=minutes)
        if arrival + timedelta(minutes=5) > start:
            continue
        ok, reason = available_for_shift(db, business, appointment, start, end, now=now)
        if ok:
            result.append({"delay_minutes": minutes, "starts_at": start.isoformat(),
                           "ends_at": end.isoformat(), "reason": reason,
                           "arrival_estimate": arrival.isoformat(),
                           "eta_source": "customer_reported", "requires_acceptance": True})
    return result
