"""Cross-industry customer intake and scoped service-provider briefings.

Supports existing SmartSlot categories: salon, clinic, repair_center and
consultant. Does NOT infer qualifications, durations or medical decisions.
The current demo authentication is not appropriate for real health information.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import admin_user, current_user
from .database import get_db
from .models import (Appointment, BookingHaircutPreference, BookingServiceIntake,
                     Business, Service, Staff)
from .queue_engine import utc
from .recovery_api import portable_booking
from .service_intake_schemas import ServiceIntakeInput

router = APIRouter(prefix="/api", tags=["Service Intake (All Industries)"])

# Stable field IDs for React form rendering. Each field is optional and
# checked server-side so a clinic cannot be sent arbitrary salon-specific data.
CATEGORY_FIELDS: dict[str, list[tuple[str, str]]] = {
    "salon": [
        ("desired_style", "Desired haircut, style or treatment"),
        ("preferred_length", "Preferred length (if relevant)"),
        ("reference_description", "Reference look or styling instructions"),
    ],
    "clinic": [
        ("visit_reason", "General reason for your appointment"),
        ("visit_type", "First visit or follow-up"),
        ("accessibility_request", "Accessibility arrangements, if needed"),
    ],
    "repair_center": [
        ("item_type", "Item or device to be repaired"),
        ("model", "Model or serial description (no passwords)"),
        ("reported_issue", "Problem or symptoms observed"),
    ],
    "consultant": [
        ("consultation_goal", "What would you like to achieve?"),
        ("project_context", "Brief background about your project"),
        ("questions", "Questions you would like to discuss"),
    ],
}


def fields_for(category: str) -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in CATEGORY_FIELDS.get(category, [
        ("request_details", "What would you like help with?"),
        ("special_requests", "Any special requests?"),
    ])]


def validate_intake(category: str, incoming: ServiceIntakeInput) -> None:
    allowed = {field["key"] for field in fields_for(category)}
    unsupported = set(incoming.answers) - allowed
    if unsupported:
        raise HTTPException(status_code=422, detail=f"Unsupported intake fields for {category}: {', '.join(sorted(unsupported))}")


def save_intake(db: Session, appointment: Appointment,
                incoming: ServiceIntakeInput) -> BookingServiceIntake:
    """Attach/update intake within caller's transaction; never commit here."""
    branch = db.get(Business, appointment.business_id)
    if not branch:
        raise HTTPException(404, "Business not found")
    validate_intake(branch.category, incoming)
    entry = db.get(BookingServiceIntake, appointment.id)
    if entry is None:
        entry = BookingServiceIntake(appointment_id=appointment.id)
        db.add(entry)
    entry.category = branch.category
    entry.summary = incoming.summary
    entry.notes = incoming.notes
    entry.answers = dict(incoming.answers)
    entry.updated_at = datetime.now(timezone.utc)
    return entry


def intake_json(intake: BookingServiceIntake | None) -> dict | None:
    if intake is None:
        return None
    return {"summary": intake.summary, "notes": intake.notes,
            "answers": dict(intake.answers or {})}


def display_intake(db: Session, booking: Appointment) -> dict | None:
    """Keep Phase 3 salon notes visible until customers migrate to new forms."""
    record = db.get(BookingServiceIntake, booking.id)
    if record is not None:
        return intake_json(record)
    prior = db.get(BookingHaircutPreference, booking.id)
    if prior is None:
        return None
    # Existing haircut notes are not altered or erased by the new feature.
    return {"summary": "Haircut preferences", "notes": prior.notes,
            "answers": {"desired_style": prior.style,
                        "preferred_length": prior.preferred_length}}


@router.get("/businesses/{business_id}/intake-template")
def intake_template(business_id: int, service_id: int,
                    db: Session = Depends(get_db)):
    branch = db.get(Business, business_id)
    if branch is None or not branch.active:
        raise HTTPException(404, "Business not found")
    service = db.scalar(select(Service).where(Service.id == service_id,
        Service.business_id == business_id, Service.active.is_(True)))
    if service is None:
        raise HTTPException(404, "Service not found for this business")
    return {"business_id": business_id, "service_id": service.id,
            "service_name": service.name, "category": branch.category,
            "fields": fields_for(branch.category),
            "summary_label": "Briefly describe your request",
            "notes_label": "Anything else the professional should know?",
            "optional": True,
            "warning": "Avoid confidential personal or medical details in demo mode."}


@router.get("/appointments/{reference}/service-intake")
def customer_service_intake(reference: str, business_id: int,
                            user=Depends(current_user), db: Session = Depends(get_db)):
    appointment = portable_booking(db, business_id, reference, user)
    branch = db.get(Business, appointment.business_id)
    return {"reference": appointment.reference, "business_id": appointment.business_id,
            "category": branch.category, "intake": display_intake(db, appointment)}


@router.put("/appointments/{reference}/service-intake")
def update_service_intake(reference: str, body: ServiceIntakeInput, business_id: int,
                          user=Depends(current_user), db: Session = Depends(get_db)):
    appointment = portable_booking(db, business_id, reference, user)
    # A row lock serializes concurrent edits and staff/branch handoffs in PostgreSQL.
    db.scalar(select(Appointment.id).where(Appointment.id == appointment.id).with_for_update())
    db.refresh(appointment)
    if appointment.status not in ("confirmed", "at_risk") or utc(appointment.starts_at) <= datetime.now(timezone.utc):
        raise HTTPException(409, "Intake can only be updated before an active appointment begins")
    intake = save_intake(db, appointment, body)
    db.commit()
    return {"reference": appointment.reference, "business_id": appointment.business_id,
            "intake": intake_json(intake)}


@router.get("/admin/appointments/{reference}/service-briefing")
def professional_briefing(reference: str, business_id: int,
                          user=Depends(admin_user), db: Session = Depends(get_db)):
    """Admin-scoped until verified professional accounts are available."""
    if business_id not in user.get("business_ids", []):
        raise HTTPException(403, "No admin access to this business")
    branch = db.get(Business, business_id)
    if branch is None or not branch.active:
        raise HTTPException(404, "Business not found")
    booking = db.scalar(select(Appointment).where(
        Appointment.business_id == business_id,
        Appointment.reference == reference))
    if booking is None:
        raise HTTPException(404, "Appointment not found for this business")
    service = db.get(Service, booking.service_id)
    staff = db.get(Staff, booking.staff_id)
    return {
        "reference": booking.reference,
        "business_id": booking.business_id,
        "business_category": branch.category,
        "customer_name": booking.customer_name,
        "status": booking.status,
        "service_name": service.name if service else "Unknown service",
        "service_duration_minutes": booking.duration_minutes,
        "staff_id": booking.staff_id,
        "staff_name": staff.name if staff else "Unassigned",
        "starts_at": utc(booking.starts_at).isoformat(),
        "intake": display_intake(db, booking),
        "note": "Customer-provided request only. Confirm details in person; no qualification, price or duration overrides.",
    }
