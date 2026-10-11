"""Customer consent + safe, explainable appointment recovery REST API.

No background GPS collection. A branch transfer requires a fresh customer GPS
update on this request; absence events can auto-reassign same-branch only.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from .auth import current_user, admin_user
from .config import settings
from .database import get_db
from .georoutes import estimate_travel, RoutingUnavailable
from .models import (
    AdminAlert, Appointment, Business, RecoveryPolicy, RecoveryEvent,
    Service, ServiceTransfer, Staff, StaffAbsence, StaffPresence
)
from .queue_engine import utc
from .recovery_engine import same_branch_candidates, branch_candidates, apply_recovery

router = APIRouter(prefix="/api", tags=["Smart Recovery"])


class PolicyUpdate(BaseModel):
    allow_staff_substitution: bool = False
    allow_branch_transfer: bool = False
    max_delay_minutes: int = Field(default=30, ge=0, le=30)


class TransferLinkCreate(BaseModel):
    source_service_id: int = Field(gt=0)
    target_service_id: int = Field(gt=0)


class RecoveryRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    captured_at: datetime | None = None
    accuracy_meters: float | None = Field(default=None, ge=0, le=10000)
    dry_run: bool = False


def owner_booking(db: Session, business_id: int, reference: str, user: dict) -> Appointment:
    if user.get("role") != "customer" or user.get("business_id") != business_id:
        raise HTTPException(403, "Customer session is not scoped to this branch")
    booking = db.scalar(select(Appointment).where(
        Appointment.business_id == business_id,
        Appointment.reference == reference,
        Appointment.customer_email == user["email"]))
    if not booking:
        raise HTTPException(404, "Booking not found")
    return booking


def ensure_admin(db: Session, business_id: int, user: dict) -> Business:
    business = db.get(Business, business_id)
    if not business or not business.active:
        raise HTTPException(404, "Business not found")
    if user.get("role") != "admin" or business_id not in user.get("business_ids", []):
        raise HTTPException(403, "Admin role required for this branch")
    return business


def get_policy(db: Session, appointment_id: int) -> RecoveryPolicy | None:
    return db.scalar(select(RecoveryPolicy).where(RecoveryPolicy.appointment_id == appointment_id))


def problem_requires_recovery(db: Session, booking: Appointment, now: datetime) -> bool:
    """Only recover appointments impacted by known/unavailability signals."""
    if booking.status not in ("confirmed", "at_risk") or utc(booking.ends_at) <= now:
        return False
    person = db.get(Staff, booking.staff_id)
    if not person or not person.active:
        return True
    absences = db.scalars(select(StaffAbsence).where(
        StaffAbsence.business_id == booking.business_id,
        StaffAbsence.staff_id == booking.staff_id,
        StaffAbsence.starts_at < booking.ends_at,
        StaffAbsence.ends_at > booking.starts_at)).all()
    if absences:
        return True
    presence = db.scalar(select(StaffPresence).where(
        StaffPresence.business_id == booking.business_id,
        StaffPresence.staff_id == booking.staff_id))
    return bool(presence and presence.status in ("break", "away")
        and utc(presence.updated_at) > now - timedelta(minutes=45)
        and utc(booking.starts_at) < now + timedelta(minutes=60))


def travel_routes(db: Session, booking: Appointment, body: RecoveryRequest, now: datetime) -> dict[int, dict]:
    if body.latitude is None or body.longitude is None or body.captured_at is None or body.accuracy_meters is None:
        return {}
    if (body.captured_at.tzinfo is None or abs((now-utc(body.captured_at)).total_seconds()) > 300
        or body.accuracy_meters > 150):
        raise HTTPException(422, "Fresh GPS coordinates accurate within 150 meters required")
    if utc(booking.starts_at) > now + timedelta(hours=6):
        raise HTTPException(409, "Cross-branch route recovery is only available within 6 hours of the visit")
    source = db.get(Business, booking.business_id)
    if not source or not source.organization_id:
        return {}
    service_links = db.scalars(select(ServiceTransfer).where(
        ServiceTransfer.organization_id == source.organization_id,
        ServiceTransfer.source_service_id == booking.service_id,
        ServiceTransfer.active.is_(True))).all()
    destination_ids = []
    for link in service_links:
        service = db.get(Service, link.target_service_id)
        target = db.get(Business, service.business_id) if service else None
        if target and target.id != source.id and target.organization_id == source.organization_id and target.active and target.latitude is not None and target.longitude is not None:
            destination_ids.append(target.id)
    if not destination_ids:
        return {}
    if not settings.tomtom_routing_api_key.strip():
        raise HTTPException(503, "Live TomTom routing not configured; original appointment retained")
    result = {}
    for target_id in sorted(set(destination_ids))[:4]:  # cap provider calls
        target = db.get(Business, target_id)
        try:
            result[target_id] = estimate_travel(body.latitude, body.longitude,
                target.latitude, target.longitude, settings.tomtom_routing_api_key)
        except RoutingUnavailable:
            continue
    return result


@router.put("/appointments/{reference}/recovery-policy")
def set_recovery_policy(reference: str, body: PolicyUpdate, business_id: int,
                        user=Depends(current_user), db: Session = Depends(get_db)):
    booking = owner_booking(db, business_id, reference, user)
    if booking.status not in ("confirmed", "at_risk"):
        raise HTTPException(409, "Inactive booking")
    if body.allow_branch_transfer and not body.allow_staff_substitution:
        raise HTTPException(422, "Branch transfer also requires permission for a qualified substitute")
    policy = get_policy(db, booking.id)
    if policy is None:
        policy = RecoveryPolicy(appointment_id=booking.id)
        db.add(policy)
    policy.allow_staff_substitution = body.allow_staff_substitution
    policy.allow_branch_transfer = body.allow_branch_transfer
    policy.max_delay_minutes = body.max_delay_minutes
    policy.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"reference": reference, "allow_staff_substitution": policy.allow_staff_substitution,
            "allow_branch_transfer": policy.allow_branch_transfer,
            "max_delay_minutes": policy.max_delay_minutes}


@router.get("/appointments/{reference}/recovery-policy")
def read_recovery_policy(reference: str, business_id: int, user=Depends(current_user),
                         db: Session = Depends(get_db)):
    booking = owner_booking(db, business_id, reference, user)
    policy = get_policy(db, booking.id)
    return {"reference": reference, "allow_staff_substitution": bool(policy and policy.allow_staff_substitution),
            "allow_branch_transfer": bool(policy and policy.allow_branch_transfer),
            "max_delay_minutes": policy.max_delay_minutes if policy else 30}


@router.post("/admin/service-transfers", status_code=201)
def configure_service_transfer(body: TransferLinkCreate, business_id: int,
                               user=Depends(admin_user), db: Session = Depends(get_db)):
    source = db.get(Service, body.source_service_id)
    target = db.get(Service, body.target_service_id)
    origin = ensure_admin(db, business_id, user)
    if not source or not target or source.id == target.id:
        raise HTTPException(422, "Two distinct services required")
    b1, b2 = db.get(Business, source.business_id), db.get(Business, target.business_id)
    if (source.business_id != origin.id or not b1.organization_id
         or b1.organization_id != b2.organization_id or b1.id == b2.id
         or b2.id not in user.get("business_ids", []) or b1.category != b2.category
         or not source.active or not target.active
         or source.duration_minutes != target.duration_minutes
         or source.price != target.price):
        raise HTTPException(422, "Both businesses must be authorized branches with compatible active services and equal duration and price")
    existing = db.scalar(select(ServiceTransfer).where(
        ServiceTransfer.source_service_id == source.id,
        ServiceTransfer.target_service_id == target.id))
    if existing:
        existing.active = True
        link = existing
    else:
        link = ServiceTransfer(organization_id=b1.organization_id,
            source_service_id=source.id, target_service_id=target.id, active=True)
        db.add(link)
    db.commit()
    return {"source_service_id": source.id, "target_service_id": target.id,
            "organization_id": link.organization_id, "active": True,
            "note": "Explicit directional transfer link; create reverse link separately if appropriate"}


def recovery_attempt(db: Session, booking: Appointment, policy: RecoveryPolicy,
                     body: RecoveryRequest, now: datetime):
    if not policy.allow_staff_substitution:
        return None, "Customer has not authorized automatic reassignment"
    if not problem_requires_recovery(db, booking, now):
        return None, "No verified disruption affecting this booking"
    options = same_branch_candidates(db, booking, policy, now)
    if options:
        return options[0], "Same-branch substitute or short delay"
    if not policy.allow_branch_transfer:
        return None, "No suitable same-branch appointment; branch transfer not authorized"
    routes = travel_routes(db, booking, body, now)
    options = branch_candidates(db, booking, policy, now, routes)
    return (options[0], "TomTom-verified compatible branch") if options else (None, "No safely reachable equivalent branch and free professional found")


@router.post("/appointments/{reference}/recover")
def recover_with_fresh_gps(reference: str, body: RecoveryRequest, business_id: int,
                           user=Depends(current_user), db: Session = Depends(get_db)):
    booking = owner_booking(db, business_id, reference, user)
    policy = get_policy(db, booking.id)
    now = datetime.now(timezone.utc)
    if not policy:
        raise HTTPException(409, "Enable automatic recovery preferences before rescheduling")
    selected, reason = recovery_attempt(db, booking, policy, body, now)
    if not selected:
        if reason != "No verified disruption affecting this booking":
            recent = db.scalar(select(AdminAlert.id).where(
                AdminAlert.business_id == booking.business_id,
                AdminAlert.reference == booking.reference,
                AdminAlert.kind == "recovery_unresolved",
                AdminAlert.created_at >= now - timedelta(minutes=15)))
            if recent is None:
                db.add(AdminAlert(business_id=booking.business_id, kind="recovery_unresolved",
                    reference=booking.reference,
                    message=f"Recovery requires review for {booking.reference}; no safe option was available."))
                db.commit()
        return {"status": "unresolved", "reference": reference, "reason": reason,
            "appointment_unchanged": True}
    if body.dry_run:
        return {"status": "candidate", "reference": reference, "candidate": selected.as_json(),
                "reason": reason, "appointment_unchanged": True}
    try:
        event = apply_recovery(db, booking, selected, reason, now)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"status": "reassigned", "reference": reference,
            "new_business_id": event.to_business_id,
            "new_staff_id": event.to_staff_id,
            "new_starts_at": utc(event.new_starts_at).isoformat(),
            "reason": reason, "new_qr_required": True}


@router.get("/admin/recovery-events")
def recovery_events(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    ensure_admin(db, business_id, user)
    events = db.scalars(select(RecoveryEvent).where(or_(
        RecoveryEvent.from_business_id == business_id,
        RecoveryEvent.to_business_id == business_id))
        .order_by(RecoveryEvent.created_at.desc(), RecoveryEvent.id.desc()).limit(100)).all()
    return [{"id": e.id, "appointment_id": e.appointment_id,
            "old_branch_id": e.from_business_id, "new_branch_id": e.to_business_id,
            "old_staff_id": e.from_staff_id, "new_staff_id": e.to_staff_id,
            "old_starts_at": utc(e.previous_starts_at).isoformat(),
            "new_starts_at": utc(e.new_starts_at).isoformat(),
            "reason": e.reason, "actor": e.actor} for e in events]


def portable_booking(db: Session, original_business_id: int, reference: str,
                     user: dict) -> Appointment:
    """Customer still owns a booking after moving to another authorized branch.

    Scopes a transferred booking through its audit record and matching email,
    not through unrestricted cross-branch access. Old customer login remains valid.
    """
    if user.get("role") != "customer" or user.get("business_id") != original_business_id:
        raise HTTPException(403, "Customer session not valid for originating branch")
    origin = db.get(Business, original_business_id)
    if not origin:
        raise HTTPException(404, "Original business not found")
    booking = db.scalar(select(Appointment).where(
        Appointment.business_id == original_business_id,
        Appointment.reference == reference,
        Appointment.customer_email == user["email"]))
    if booking:
        return booking
    target = db.scalar(select(Appointment).join(
        RecoveryEvent, RecoveryEvent.appointment_id == Appointment.id).where(
        RecoveryEvent.from_business_id == original_business_id,
        Appointment.reference == reference,
        Appointment.customer_email == user["email"])
        .order_by(RecoveryEvent.id.desc()).limit(1))
    destination = db.get(Business, target.business_id) if target else None
    if (target and destination and origin.organization_id is not None
         and destination.organization_id == origin.organization_id):
        return target
    raise HTTPException(404, "Booking not found for this customer or organization")


@router.get("/appointments/{reference}/recovery-status")
def customer_recovery_status(reference: str, business_id: int,
                             user=Depends(current_user), db: Session = Depends(get_db)):
    appointment = portable_booking(db, business_id, reference, user)
    branch = db.get(Business, appointment.business_id)
    staff = db.get(Staff, appointment.staff_id)
    service = db.get(Service, appointment.service_id)
    return {"reference": reference, "status": appointment.status,
            "business_id": branch.id, "business_name": branch.name,
            "latitude": branch.latitude, "longitude": branch.longitude,
            "staff_name": staff.name, "service_name": service.name,
            "starts_at": utc(appointment.starts_at).isoformat(),
            "ends_at": utc(appointment.ends_at).isoformat(),
            "qr_needs_reissue": bool(db.scalar(select(RecoveryEvent.id).where(
                RecoveryEvent.appointment_id == appointment.id)))}


@router.post("/appointments/{reference}/recovery-qr")
def customer_recovery_qr(reference: str, business_id: int,
                         user=Depends(current_user), db: Session = Depends(get_db)):
    """New owner-only QR at destination, available on appointment day only."""
    from datetime import time
    from zoneinfo import ZoneInfo
    from .qr import create_pass, token_hash
    appointment = portable_booking(db, business_id, reference, user)
    db.scalar(select(Appointment.id).where(Appointment.id == appointment.id).with_for_update())
    db.refresh(appointment)
    branch = db.get(Business, appointment.business_id)
    origin = db.get(Business, business_id)
    if not branch or not origin or (branch.id != origin.id and (
            not origin.organization_id or origin.organization_id != branch.organization_id)):
        raise HTTPException(409, "Appointment changed organizations while issuing its pass")
    now = datetime.now(timezone.utc)
    if (appointment.status not in ("confirmed", "at_risk") or
        utc(appointment.ends_at) <= now or
        now.astimezone(ZoneInfo(branch.timezone)).date() <
        utc(appointment.starts_at).astimezone(ZoneInfo(branch.timezone)).date()):
        raise HTTPException(409, "Real QR is issued only on an active appointment day")
    secret, qr_image = create_pass()
    appointment.qr_token_hash = token_hash(secret)
    db.commit()
    return {"reference": reference, "business_id": branch.id,
            "qr_token": secret, "qr_image": qr_image,
            "note": "Previous QR invalidated; protect this pass like a ticket"}
