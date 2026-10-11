"""Customer haircut notes and an access-controlled read-only stylist briefing.

No photos are uploaded in v1. Notes are preferences, not instructions to override
service duration, barber qualifications, pricing, or customer consent.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import admin_user, current_user
from .database import get_db
from .haircut_schemas import HaircutPreferencesInput
from .models import Appointment, BookingHaircutPreference, Business, Service, Staff
from .queue_engine import utc
from .recovery_api import portable_booking

router = APIRouter(prefix="/api", tags=["Haircut Consultation"])


def put_preferences(db: Session, appointment: Appointment,
                    incoming: HaircutPreferencesInput) -> BookingHaircutPreference:
    """Update in caller's transaction. Does not commit or change allocation."""
    branch = db.get(Business, appointment.business_id)
    if not branch or branch.category != "salon":
        raise HTTPException(422, "Haircut preferences are available only for salon bookings")
    value = db.get(BookingHaircutPreference, appointment.id)
    if value is None:
        value = BookingHaircutPreference(appointment_id=appointment.id)
        db.add(value)
    value.style = incoming.style
    value.preferred_length = incoming.preferred_length
    value.notes = incoming.notes
    value.updated_at = datetime.now(timezone.utc)
    return value


def preference_json(value: BookingHaircutPreference | None) -> dict | None:
    if value is None:
        return None
    return {"style": value.style, "preferred_length": value.preferred_length,
            "notes": value.notes}


def customer_appointment(db: Session, business_id: int, reference: str, user: dict) -> Appointment:
    booking = portable_booking(db, business_id, reference, user)
    business = db.get(Business, booking.business_id)
    if not business or business.category != "salon":
        raise HTTPException(422, "Haircut preferences are available only for salon bookings")
    return booking


@router.get("/appointments/{reference}/haircut-preferences")
def customer_preferences(reference: str, business_id: int,
                         user=Depends(current_user), db: Session = Depends(get_db)):
    appointment = customer_appointment(db, business_id, reference, user)
    return {"reference": appointment.reference, "business_id": appointment.business_id,
            "preferences": preference_json(db.get(BookingHaircutPreference, appointment.id))}


@router.put("/appointments/{reference}/haircut-preferences")
def update_customer_preferences(reference: str, body: HaircutPreferencesInput, business_id: int,
                                user=Depends(current_user), db: Session = Depends(get_db)):
    appointment = customer_appointment(db, business_id, reference, user)
    # Serialize concurrent preference edits and re-read the latest booking state.
    db.scalar(select(Appointment.id).where(Appointment.id == appointment.id).with_for_update())
    db.refresh(appointment)
    if appointment.status not in ("confirmed", "at_risk") or utc(appointment.starts_at) <= datetime.now(timezone.utc):
        raise HTTPException(409, "Haircut preferences can only be changed before an active appointment starts")
    value = put_preferences(db, appointment, body)
    db.commit()
    return {"reference": appointment.reference, "business_id": appointment.business_id,
            "preferences": preference_json(value)}


@router.get("/admin/appointments/{reference}/stylist-briefing")
def stylist_briefing(reference: str, business_id: int,
                     user=Depends(admin_user), db: Session = Depends(get_db)):
    """Reception/stylist-facing details (admin auth until staff auth is added)."""
    if business_id not in user.get("business_ids", []):
        raise HTTPException(403, "No admin access to this salon")
    branch = db.get(Business, business_id)
    if not branch or not branch.active or branch.category != "salon":
        raise HTTPException(404, "Salon not found")
    booking = db.scalar(select(Appointment).where(
        Appointment.business_id == business_id,
        Appointment.reference == reference))
    if booking is None:
        raise HTTPException(404, "Appointment not found for this salon")
    service = db.get(Service, booking.service_id)
    person = db.get(Staff, booking.staff_id)
    return {
        "reference": booking.reference,
        "business_id": booking.business_id,
        "customer_name": booking.customer_name,
        "status": booking.status,
        "service_name": service.name if service else "Unknown service",
        "service_duration_minutes": booking.duration_minutes,
        "staff_id": booking.staff_id,
        "staff_name": person.name if person else "Unassigned",
        "starts_at": utc(booking.starts_at).isoformat(),
        "preferences": preference_json(db.get(BookingHaircutPreference, booking.id)),
        "note": "Customer wishes only; confirm details in person. Service duration and qualifications are unchanged.",
    }
