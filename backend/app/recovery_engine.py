"""AETHERX Smart Recovery v1.

Same-branch substitution first, small local delay next, and transfer to an
explicitly equivalent service in another organization branch only with fresh
customer GPS and advance opt-in. No background tracking or speculative travel.

The engine never commits: API callers commit the appointment, audit and alerts
in ONE transaction. PostgreSQL serializes participating staff with row locks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Appointment, Business, Staff, Service, StaffService, StaffAbsence,
    StaffPresence, SlotOffer, RecoveryPolicy, ServiceTransfer, RecoveryEvent,
    AdminAlert,
)
from .queue_engine import ACTIVE, is_staff_working, overlaps, utc
from .qr import token_hash
from .waitlist import notify


@dataclass(frozen=True)
class Candidate:
    business_id: int
    service_id: int
    staff_id: int
    starts_at: datetime
    ends_at: datetime
    buffer_minutes: int
    priority: int  # 0=same time, 1=short delay, 2=other branch
    eta_minutes: int | None = None
    distance_km: float | None = None

    def as_json(self):
        return {"business_id": self.business_id, "service_id": self.service_id,
                "staff_id": self.staff_id, "starts_at": utc(self.starts_at).isoformat(),
                "ends_at": utc(self.ends_at).isoformat(), "priority": self.priority,
                "eta_minutes": self.eta_minutes, "distance_km": self.distance_km}


def candidate_available(db: Session, booking: Appointment, business: Business,
                        service: Service, staff: Staff, start: datetime,
                        now: datetime, *, ignore_booking_id: int) -> bool:
    """Check precise time intervals, not only coarse 30-minute calendar slots."""
    start = utc(start)
    if not (business.active and service.active and staff.active and
            service.business_id == business.id and staff.business_id == business.id and
            db.get(StaffService, (staff.id, service.id))):
        return False
    if start < now + timedelta(minutes=5):
        return False
    end = start + timedelta(minutes=service.duration_minutes)
    interval_buffer = business.default_buffer_minutes + service.buffer_minutes
    fake = SimpleNamespace(staff_id=staff.id, service_id=service.id)
    if not is_staff_working(db, business, fake, start, end):
        return False
    presence = db.scalar(select(StaffPresence).where(
        StaffPresence.business_id == business.id, StaffPresence.staff_id == staff.id))
    if (presence and presence.status in ("break", "away")
            and utc(presence.updated_at) > now - timedelta(minutes=45)
            and start < now + timedelta(minutes=60)):
        return False
    for absence in db.scalars(select(StaffAbsence).where(
            StaffAbsence.staff_id == staff.id, StaffAbsence.business_id == business.id,
            StaffAbsence.starts_at < end + timedelta(minutes=interval_buffer),
            StaffAbsence.ends_at > start)).all():
        if utc(absence.starts_at) < end + timedelta(minutes=interval_buffer) and utc(absence.ends_at) > start:
            return False
    for other in db.scalars(select(Appointment).where(
            Appointment.staff_id == staff.id,
            Appointment.id != ignore_booking_id,
            Appointment.status.in_(ACTIVE),
            Appointment.starts_at < end + timedelta(minutes=interval_buffer),
            Appointment.ends_at > start - timedelta(days=1))).all():
        if overlaps(start, end, interval_buffer, other.starts_at, other.ends_at, other.buffer_minutes):
            return False
    for hold in db.scalars(select(SlotOffer).where(
            SlotOffer.staff_id == staff.id, SlotOffer.status == "pending",
            SlotOffer.expires_at > now)).all():
        if hold.appointment_id == ignore_booking_id and hold.kind != "waitlist":
            continue
        if overlaps(start, end, interval_buffer, hold.starts_at, hold.ends_at, interval_buffer):
            return False
    return True


def same_branch_candidates(db: Session, booking: Appointment, policy: RecoveryPolicy,
                           now: datetime) -> list[Candidate]:
    business = db.get(Business, booking.business_id)
    service = db.get(Service, booking.service_id)
    if not (business and service and policy.allow_staff_substitution):
        return []
    staff = db.scalars(select(Staff).join(StaffService, StaffService.staff_id == Staff.id)
        .where(Staff.business_id == business.id, StaffService.service_id == service.id,
               Staff.active.is_(True))
        .order_by(Staff.id)).all()
    result = []
    original = utc(booking.starts_at)
    for person in staff:
        for delta in (0, 15, 30):
            if person.id == booking.staff_id and delta == 0:
                continue  # no-op is not recovery
            if delta > policy.max_delay_minutes:
                continue
            start = original + timedelta(minutes=delta)
            if candidate_available(db, booking, business, service, person, start, now,
                                   ignore_booking_id=booking.id):
                result.append(Candidate(business.id, service.id, person.id, start,
                    start + timedelta(minutes=service.duration_minutes),
                    business.default_buffer_minutes + service.buffer_minutes,
                    0 if delta == 0 else 1))
    # Prefer zero delay, then the smallest delay, then deterministic staff id.
    return sorted(result, key=lambda c: (c.priority, utc(c.starts_at), c.staff_id))


def branch_candidates(db: Session, booking: Appointment, policy: RecoveryPolicy,
                      now: datetime, routes: dict[int, dict]) -> list[Candidate]:
    """Routes must be real, fresh TomTom route results supplied by the caller.

    Explicit ServiceTransfer rows are mandatory; matching a service name alone
    is NOT evidence two branches offer equivalent treatments.
    """
    source = db.get(Business, booking.business_id)
    if not (policy.allow_branch_transfer and source and source.organization_id and routes):
        return []
    links = db.scalars(select(ServiceTransfer).where(
        ServiceTransfer.source_service_id == booking.service_id,
        ServiceTransfer.organization_id == source.organization_id,
        ServiceTransfer.active.is_(True))).all()
    results = []
    for link in links:
        service = db.get(Service, link.target_service_id)
        target = db.get(Business, service.business_id) if service else None
        if not (target and target.id != source.id and target.organization_id == source.organization_id and target.active and service.active):
            continue
        original_service = db.get(Service, booking.service_id)
        if service.duration_minutes != booking.duration_minutes or service.price != original_service.price:
            continue   # do not silently change treatment duration or price
        route = routes.get(target.id)
        if not route or route.get("source") != "tomtom_live_traffic" or not route.get("traffic_aware"):
            continue
        eta = route.get("eta_minutes")
        distance = route.get("distance_km")
        if not isinstance(eta, int) or eta < 0 or eta > 180:
            continue
        if not isinstance(distance, (int, float)) or distance < 0:
            continue
        personnel = db.scalars(select(Staff).join(StaffService, StaffService.staff_id == Staff.id)
            .where(Staff.business_id == target.id, StaffService.service_id == service.id,
                   Staff.active.is_(True)).order_by(Staff.id)).all()
        for delta in (0, 15, 30):
            if delta > policy.max_delay_minutes:
                continue
            start = utc(booking.starts_at) + timedelta(minutes=delta)
            # Extra time for reaching the reception/check-in desk.
            if now + timedelta(minutes=eta + 5) > start:
                continue
            for person in personnel:
                if candidate_available(db, booking, target, service, person, start, now,
                                       ignore_booking_id=booking.id):
                    results.append(Candidate(target.id, service.id, person.id, start,
                        start + timedelta(minutes=service.duration_minutes),
                        target.default_buffer_minutes + service.buffer_minutes, 2, eta, float(distance)))
    return sorted(results, key=lambda c: (utc(c.starts_at), c.eta_minutes, c.distance_km, c.staff_id))


def apply_recovery(db: Session, booking: Appointment, selected: Candidate,
                   reason: str, now: datetime) -> RecoveryEvent:
    """Commit-ready atomic change. Staff rows locked in deterministic ID order.

    The caller must call db.commit(); if anything fails, no change is persisted.
    PostgreSQL staff-row locks serialize this flow with ordinary booking/absence
    writes. Existing SQL query checks are repeated AFTER acquiring the locks.
    """
    now = utc(now)
    expected = (booking.business_id, booking.staff_id, booking.service_id,
                utc(booking.starts_at), booking.status)
    # Lock source and destination staff consistently across competing recoveries.
    staff_ids = sorted({booking.staff_id, selected.staff_id})
    locked = db.scalars(select(Staff).where(Staff.id.in_(staff_ids)).order_by(Staff.id).with_for_update()).all()
    if len(locked) != len(staff_ids):
        raise ValueError("Staff no longer available")
    fresh = db.scalar(select(Appointment).where(Appointment.id == booking.id).with_for_update())
    if fresh is None:
        raise ValueError("Appointment disappeared during recovery")
    # Under READ COMMITTED, refresh the identity-map object *after* acquiring
    # its row lock. Otherwise an earlier ORM read can hide a competing transfer.
    db.refresh(fresh)
    if fresh.status not in ("confirmed", "at_risk"):
        raise ValueError("Appointment changed; recovery not permitted")
    if (fresh.business_id, fresh.staff_id, fresh.service_id,
            utc(fresh.starts_at), fresh.status) != expected:
        raise ValueError("Appointment was modified by another transaction")
    target = db.get(Business, selected.business_id)
    service = db.get(Service, selected.service_id)
    staff = db.get(Staff, selected.staff_id)
    policy = db.scalar(select(RecoveryPolicy).where(RecoveryPolicy.appointment_id == fresh.id).with_for_update())
    if not policy or not policy.allow_staff_substitution:
        raise ValueError("Customer has not opted in to professional substitution")
    if target.id != fresh.business_id and not policy.allow_branch_transfer:
        raise ValueError("Customer has not opted in to branch transfers")
    if utc(selected.starts_at) < utc(fresh.starts_at) or utc(selected.starts_at) > utc(fresh.starts_at) + timedelta(minutes=policy.max_delay_minutes):
        raise ValueError("Selected time exceeds the customer's delay limit")
    if target.id != fresh.business_id:
        original_service = db.get(Service, fresh.service_id)
        # Never silently switch to a service with a different disclosed price.
        if service.price != original_service.price or service.duration_minutes != original_service.duration_minutes:
            raise ValueError("Branch services must have identical duration and price")
        src = db.get(Business, fresh.business_id)
        mapping = db.scalar(select(ServiceTransfer.id).where(
            ServiceTransfer.organization_id == src.organization_id,
            ServiceTransfer.source_service_id == fresh.service_id,
            ServiceTransfer.target_service_id == selected.service_id,
            ServiceTransfer.active.is_(True)))
        if not src.organization_id or src.organization_id != target.organization_id or not mapping:
            raise ValueError("Branches or services are not explicitly linked")
        if db.scalar(select(Appointment.id).where(
                Appointment.business_id == target.id,
                Appointment.reference == fresh.reference,
                Appointment.id != fresh.id)):
            raise ValueError("Booking reference collision at destination")
    # Route estimates must remain reachable at the instant we commit.
    decision_now = datetime.now(timezone.utc)
    if (selected.eta_minutes is not None and
        decision_now + timedelta(minutes=selected.eta_minutes + 5) > utc(selected.starts_at)):
        raise ValueError("Traffic ETA is now too late for the target appointment")
    if not candidate_available(db, fresh, target, service, staff, selected.starts_at, decision_now,
                               ignore_booking_id=fresh.id):
        raise ValueError("Candidate slot became unavailable")
    old_business_id, old_service_id, old_staff_id = fresh.business_id, fresh.service_id, fresh.staff_id
    old_start = utc(fresh.starts_at)
    fresh.business_id = selected.business_id
    fresh.service_id = selected.service_id
    fresh.staff_id = selected.staff_id
    fresh.starts_at = utc(selected.starts_at)
    fresh.ends_at = utc(selected.ends_at)
    fresh.buffer_minutes = selected.buffer_minutes
    # Rotate any previously activated QR: old pass is no longer valid.
    fresh.qr_token_hash = token_hash(secrets.token_urlsafe(32))
    event = RecoveryEvent(appointment_id=fresh.id, from_business_id=old_business_id,
        to_business_id=fresh.business_id, from_service_id=old_service_id, to_service_id=fresh.service_id,
        from_staff_id=old_staff_id, to_staff_id=fresh.staff_id,
        previous_starts_at=old_start, new_starts_at=utc(fresh.starts_at),
        reason=reason, actor="auto_engine", created_at=now)
    db.add(event)
    db.add(AdminAlert(business_id=old_business_id, kind="auto_recovery", reference=fresh.reference,
        message=f"Auto recovery: {fresh.reference} reassigned; new business {fresh.business_id}, staff {fresh.staff_id}, time {utc(fresh.starts_at).isoformat()}."))
    if old_business_id != fresh.business_id:
        db.add(AdminAlert(business_id=fresh.business_id, kind="incoming_transfer", reference=fresh.reference,
            message=f"Incoming transfer {fresh.reference} from branch {old_business_id}; verify customer identity at reception."))
    notify(db, old_business_id, fresh.customer_email,
           f"SmartSlot updated {fresh.reference}: branch {target.name}, time {utc(fresh.starts_at).isoformat()}. Your old QR is invalid; open QR Passes on visit day for a new pass.")
    if old_business_id != fresh.business_id:
        notify(db, fresh.business_id, fresh.customer_email,
               f"SmartSlot transfer {fresh.reference}: now at {target.name}. Open the new branch in SmartSlot.")
    return event
