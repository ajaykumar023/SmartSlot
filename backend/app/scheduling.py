from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .models import Appointment, Availability, Business, BusinessHours, Service, Staff, StaffService, StaffAbsence, SlotOffer
from .queue_engine import utc

CATEGORY_LABELS = {"salon": "Salon", "clinic": "Clinic", "repair_center": "Repair Center", "consultant": "Consultant"}
STAFF_LABELS = {"salon": "Stylist", "clinic": "Doctor", "repair_center": "Technician", "consultant": "Consultant"}


def business_json(business: Business) -> dict:
    return {"id": business.id, "name": business.name, "category": business.category,
        "category_label": CATEGORY_LABELS.get(business.category, "Appointment business"),
        "description": business.description, "timezone": business.timezone,
        "staff_label": STAFF_LABELS.get(business.category, "Staff member")}


def candidate_slots(db: Session, business: Business, service_id: int, date_from: date, date_to: date,
                    staff_id: int | None = None, exclude_offer_id: int | None = None) -> list[dict]:
    if not business.active:
        return []
    if (date_to - date_from).days < 0 or (date_to - date_from).days > 30:
        raise ValueError("Choose a date range up to 31 days long")
    service = db.scalar(select(Service).where(Service.id == service_id, Service.business_id == business.id, Service.active.is_(True)))
    if not service:
        return []
    timezone = ZoneInfo(business.timezone)
    total_buffer = business.default_buffer_minutes + service.buffer_minutes
    staff_query = select(Staff).join(StaffService, StaffService.staff_id == Staff.id).where(
        StaffService.service_id == service.id, Staff.business_id == business.id, Staff.active.is_(True))
    if staff_id is not None:
        staff_query = staff_query.where(Staff.id == staff_id)
    staff = db.scalars(staff_query.order_by(Staff.id)).all()
    results: list[dict] = []
    day = date_from
    now = datetime.now(timezone)
    while day <= date_to:
        business_hours = db.scalar(select(BusinessHours).where(BusinessHours.business_id == business.id, BusinessHours.weekday == day.weekday()))
        if business_hours:
            business_open = datetime.combine(day, business_hours.opens_at, timezone)
            business_close = datetime.combine(day, business_hours.closes_at, timezone)
            for person in staff:
                shift = db.scalar(select(Availability).where(Availability.business_id == business.id,
                    Availability.staff_id == person.id, Availability.weekday == day.weekday()))
                if not shift:
                    continue
                shift_open = datetime.combine(day, shift.start_time, timezone)
                shift_close = datetime.combine(day, shift.end_time, timezone)
                cursor = max(business_open, shift_open)
                close = min(business_close, shift_close)
                existing = db.scalars(select(Appointment).where(
                    Appointment.business_id == business.id, Appointment.staff_id == person.id,
                    Appointment.status.in_(["confirmed", "checked_in", "at_risk"]),
                    Appointment.starts_at < close + timedelta(days=1),
                    Appointment.ends_at > cursor - timedelta(days=1),
                )).all()
                # Active waitlist offers reserve released slots until expiry.
                holds = db.scalars(select(SlotOffer).where(SlotOffer.business_id == business.id,
                    SlotOffer.staff_id == person.id, SlotOffer.kind == "waitlist",
                    SlotOffer.status == "pending", SlotOffer.expires_at > now)).all()
                # Scheduled breaks/leave block new bookings, including buffer time.
                absences = db.scalars(select(StaffAbsence).where(
                    StaffAbsence.business_id == business.id,
                    StaffAbsence.staff_id == person.id,
                    StaffAbsence.starts_at < close + timedelta(minutes=total_buffer),
                    StaffAbsence.ends_at > cursor,
                )).all()
                # Slots start every 30 minutes. Appointment and buffer intervals are both authoritative.
                while cursor + timedelta(minutes=service.duration_minutes) <= close:
                    end = cursor + timedelta(minutes=service.duration_minutes)
                    occupied_until = end + timedelta(minutes=total_buffer)
                    if cursor >= now + timedelta(minutes=15):
                        conflict = any(utc(cursor) < utc(appointment.ends_at) + timedelta(minutes=appointment.buffer_minutes)
                            and utc(appointment.starts_at) < utc(occupied_until) for appointment in existing)
                        # Exclude pending waitlist holds from ordinary customer bookings.
                        conflict = conflict or any(utc(cursor) < utc(offer.ends_at) + timedelta(minutes=total_buffer)
                            and utc(offer.starts_at) < utc(occupied_until) for offer in holds if offer.id != exclude_offer_id)
                        conflict = conflict or any(
                            utc(cursor) < utc(absence.ends_at) and
                            utc(absence.starts_at) < utc(occupied_until)
                            for absence in absences)
                        if not conflict:
                            results.append({"business_id": business.id, "service_id": service.id,
                                "duration_minutes": service.duration_minutes, "buffer_minutes": total_buffer,
                                "staff_id": person.id, "staff_name": person.name, "staff_title": person.title,
                                "starts_at": cursor.isoformat(), "ends_at": end.isoformat()})
                    cursor += timedelta(minutes=30)
        day += timedelta(days=1)
    return sorted(results, key=lambda slot: (slot["starts_at"], slot["staff_id"]))
