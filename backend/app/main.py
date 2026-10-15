from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import secrets
import string
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .auth import admin_user, current_user, issue_token
from .config import settings
from .database import get_db
from .models import Appointment, Availability, Business, BusinessHours, Notification, Service, SlotOffer, Staff, StaffService, WaitlistEntry
from .qr import create_pass, token_hash
from .schemas import BookingCreate, DemoLogin, HoursUpdate, SelfCheckInRequest, ServiceCreate, ServiceUpdate, StaffCreate, StaffUpdate, WaitlistCreate
from .scheduling import business_json, candidate_slots, in_business_timezone, in_utc_timezone, is_service_slot_within_hours
from .waitlist import match_waitlist, notify

app = FastAPI(title="SmartSlot API", version="2.0.0", description="Multi-industry appointment booking and check-in.")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def get_business(db: Session, business_id: int, require_active: bool = True) -> Business:
    business = db.get(Business, business_id)
    if not business or (require_active and not business.active):
        raise HTTPException(404, "Business not found")
    return business


def scope_business(db: Session, user: dict, business_id: int, require_admin: bool = False) -> Business:
    business = get_business(db, business_id)
    if require_admin or user.get("role") == "admin":
        if user.get("role") != "admin" or business_id not in user.get("business_ids", []):
            raise HTTPException(403, "You do not have access to this business")
    elif user.get("role") != "customer" or user.get("business_id") != business_id:
        raise HTTPException(403, "Select this business and sign in to continue")
    return business


def require_customer(user: dict):
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer access required")


def check_in_appointment(db: Session, business: Business, row: Appointment) -> Appointment:
    if row.status == "checked_in":
        raise HTTPException(409, "Appointment is already checked in")
    if row.status not in ("confirmed", "at_risk"):
        raise HTTPException(409, f"Cannot check in a {row.status} booking")
    now = datetime.now(timezone.utc)
    starts_at = in_business_timezone(row.starts_at, ZoneInfo(business.timezone)).astimezone(timezone.utc)
    ends_at = in_business_timezone(row.ends_at, ZoneInfo(business.timezone)).astimezone(timezone.utc)
    if starts_at > now + timedelta(minutes=business.check_in_minutes):
        raise HTTPException(409, f"Check-in opens {business.check_in_minutes} minutes before the appointment")
    if ends_at < now:
        raise HTTPException(409, "This appointment has ended")
    row.status, row.checked_in_at = "checked_in", now
    db.commit()
    return row


def appointment_json(db: Session, item: Appointment, include_pass: bool = False) -> dict:
    service = db.get(Service, item.service_id)
    staff = db.get(Staff, item.staff_id)
    business = db.get(Business, item.business_id)
    business_timezone = ZoneInfo(business.timezone)
    starts_at = in_business_timezone(item.starts_at, business_timezone)
    ends_at = in_business_timezone(item.ends_at, business_timezone)
    result = {"id": item.id, "reference": item.reference, "business_id": item.business_id,
        "business_name": business.name, "business_category": business.category,
        "business_timezone": business.timezone, "service_id": item.service_id,
        "service_name": service.name if service else "Service unavailable",
        "staff_id": item.staff_id, "staff_name": staff.name if staff else "Unassigned",
        "staff_title": staff.title if staff else "Staff member", "customer_name": item.customer_name,
        "customer_email": item.customer_email, "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(), "duration_minutes": item.duration_minutes,
        "buffer_minutes": item.buffer_minutes, "status": item.status}
    if include_pass:
        result["qr_token"] = getattr(item, "_raw_qr", None)
        result["qr_image"] = getattr(item, "_qr_image", None)
    return result


def service_json(service: Service) -> dict:
    return {"id": service.id, "business_id": service.business_id, "name": service.name,
        "description": service.description, "duration_minutes": service.duration_minutes,
        "buffer_minutes": service.buffer_minutes, "price": service.price, "active": service.active}


@app.get("/api/health")
def health():
    return {"status": "ok", "database": "configured", "product": "SmartSlot"}


@app.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
        db.scalars(select(Business.id).limit(1)).first()
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        raise HTTPException(503, "Database unavailable") from exc


@app.get("/api/businesses")
def businesses(db: Session = Depends(get_db)):
    rows = db.scalars(select(Business).where(Business.active.is_(True), Business.is_demo.is_(True)).order_by(Business.id)).all()
    return [business_json(row) for row in rows]


@app.get("/api/businesses/{business_id}")
def business_detail(business_id: int, db: Session = Depends(get_db)):
    business = get_business(db, business_id)
    if not business.is_demo:
        raise HTTPException(404, "Business not found")
    return business_json(business)


@app.post("/api/auth/demo")
def demo_login(body: DemoLogin, db: Session = Depends(get_db)):
    business = get_business(db, body.business_id)
    if not business.is_demo:
        raise HTTPException(404, "Demo business not found")
    if body.role == "admin":
        if body.email.lower() != "admin@smartslot.demo":
            raise HTTPException(401, "Use the demo admin identity")
        business_ids = db.scalars(select(Business.id).where(Business.active.is_(True), Business.is_demo.is_(True))).all()
    else:
        business_ids = [business.id]
    user = {"role": body.role, "name": body.name, "email": body.email.lower(), "business_id": business.id}
    token = issue_token(body.role, body.name, body.email, business.id, business_ids)
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/api/services")
def services(business_id: int, db: Session = Depends(get_db)):
    business = get_business(db, business_id)
    if not business.is_demo:
        raise HTTPException(404, "Business not found")
    rows = db.scalars(select(Service).where(Service.business_id == business.id, Service.active.is_(True)).order_by(Service.name, Service.id)).all()
    return [service_json(row) for row in rows]


@app.get("/api/staff")
def staff_list(business_id: int, service_id: int | None = None, db: Session = Depends(get_db)):
    business = get_business(db, business_id)
    stmt = select(Staff).where(Staff.business_id == business.id, Staff.active.is_(True))
    if service_id is not None:
        service = db.scalar(select(Service).where(Service.id == service_id, Service.business_id == business.id, Service.active.is_(True)))
        if not service:
            raise HTTPException(404, "Service not found for this business")
        stmt = stmt.join(StaffService, StaffService.staff_id == Staff.id).where(StaffService.service_id == service_id)
    rows = db.scalars(stmt.order_by(Staff.name, Staff.id)).unique().all()
    return [{"id": row.id, "business_id": row.business_id, "name": row.name, "title": row.title,
        "active": row.active, "service_ids": db.scalars(select(StaffService.service_id).where(StaffService.staff_id == row.id)).all()} for row in rows]


@app.get("/api/slots")
def slots(business_id: int, service_id: int, date_from: date, date_to: date,
          staff_id: int | None = None, db: Session = Depends(get_db)):
    business = get_business(db, business_id)
    try:
        return candidate_slots(db, business, service_id, date_from, date_to, staff_id)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(400, str(exc) or "Invalid business timezone") from exc


@app.post("/api/appointments", status_code=201)
def create_appointment(body: BookingCreate, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    if body.starts_at.tzinfo is None or body.starts_at.utcoffset() is None:
        raise HTTPException(422, "Appointment start time must include a timezone offset")
    if body.email.lower() != user["email"]:
        raise HTTPException(403, "Book using the email on your customer session")
    service = db.scalar(select(Service).where(Service.id == body.service_id,
        Service.business_id == business.id, Service.active.is_(True)))
    if not service:
        raise HTTPException(404, "Service not found for this business")
    try:
        possible = candidate_slots(db, business, body.service_id, body.starts_at.astimezone(ZoneInfo(business.timezone)).date(),
            body.starts_at.astimezone(ZoneInfo(business.timezone)).date(), body.staff_id)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(400, "Invalid booking date or business timezone") from exc
    match = next((slot for slot in possible if datetime.fromisoformat(slot["starts_at"]).astimezone(timezone.utc) == body.starts_at.astimezone(timezone.utc)), None)
    if not match:
        raise HTTPException(409, "That time is no longer available. Refresh the slot list and choose again.")
    staff_id = match["staff_id"]
    db.scalar(select(Staff.id).where(Staff.id == staff_id, Staff.business_id == business.id).with_for_update())
    possible = candidate_slots(db, business, service.id, body.starts_at.astimezone(ZoneInfo(business.timezone)).date(),
        body.starts_at.astimezone(ZoneInfo(business.timezone)).date(), staff_id)
    match = next((slot for slot in possible if datetime.fromisoformat(slot["starts_at"]).astimezone(timezone.utc) == body.starts_at.astimezone(timezone.utc)), None)
    if not match:
        db.rollback()
        raise HTTPException(409, "That time was just booked. Refresh the slot list and choose again.")
    token, image = create_pass()
    reference = "SS-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    row = Appointment(business_id=business.id, service_id=service.id, staff_id=staff_id,
        customer_email=user["email"], customer_name=body.name, reference=reference,
        qr_token_hash=token_hash(token), starts_at=datetime.fromisoformat(match["starts_at"]),
        ends_at=datetime.fromisoformat(match["ends_at"]), duration_minutes=service.duration_minutes,
        buffer_minutes=business.default_buffer_minutes + service.buffer_minutes, status="confirmed")
    db.add(row)
    db.flush()
    notify(db, business.id, row.customer_email, f"{business.name}: booking {reference} is confirmed. Check in with your QR pass.")
    db.commit()
    db.refresh(row)
    row._raw_qr, row._qr_image = token, image
    return appointment_json(db, row, include_pass=True)


@app.get("/api/appointments/mine")
def my_appointments(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.customer_email == user["email"]).order_by(Appointment.starts_at.desc()).limit(100)).all()
    return [appointment_json(db, row) for row in rows]


@app.post("/api/appointments/self-check-in")
def customer_self_check_in(body: SelfCheckInRequest, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = get_business(db, user["business_id"])
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.qr_token_hash == token_hash(body.token),
        Appointment.customer_email == user["email"]).with_for_update())
    if not row:
        raise HTTPException(404, "QR pass not found for this customer")
    checked_in = check_in_appointment(db, business, row)
    return appointment_json(db, checked_in)


@app.get("/api/appointments/{reference}")
def get_appointment(reference: str, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id, Appointment.reference == reference))
    if not row or (user["role"] == "customer" and row.customer_email != user["email"]):
        raise HTTPException(404, "Booking not found")
    if user["role"] == "admin" and business.id not in user.get("business_ids", []):
        raise HTTPException(403, "You do not have access to this business")
    return appointment_json(db, row)


@app.post("/api/appointments/{reference}/cancel")
def cancel_appointment(reference: str, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]).with_for_update())
    if not row:
        raise HTTPException(404, "Booking not found")
    starts_at = in_business_timezone(row.starts_at, ZoneInfo(business.timezone))
    if row.status != "confirmed" or starts_at <= datetime.now(ZoneInfo(business.timezone)) + timedelta(hours=business.cancellation_cutoff_hours):
        raise HTTPException(409, f"Bookings can be cancelled up to {business.cancellation_cutoff_hours} hours before the start time")
    row.status = "cancelled"
    db.flush()
    match_waitlist(db, row, business)
    db.commit()
    return appointment_json(db, row)


@app.post("/api/waitlist", status_code=201)
def join_waitlist(body: WaitlistCreate, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    if body.email.lower() != user["email"]:
        raise HTTPException(403, "Use the email on your customer session")
    service = db.scalar(select(Service).where(Service.id == body.service_id,
        Service.business_id == business.id, Service.active.is_(True)))
    if not service:
        raise HTTPException(404, "Service not found for this business")
    row = WaitlistEntry(business_id=business.id, service_id=service.id,
        customer_email=user["email"], customer_name=body.name, preferred_date=body.preferred_date.isoformat())
    db.add(row)
    db.commit()
    return {"id": row.id, "business_id": business.id, "status": row.status, "message": "You are on the waitlist. Review any matching offer before it expires."}


@app.get("/api/notifications")
def notifications(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    rows = db.scalars(select(Notification).where(Notification.business_id == business.id,
        Notification.customer_email == user["email"]).order_by(Notification.created_at.desc()).limit(50)).all()
    return [{"id": n.id, "message": n.message, "simulated": n.simulated, "read": n.read,
        "created_at": n.created_at.isoformat()} for n in rows]


@app.get("/api/admin/dashboard")
def dashboard(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    now_local = datetime.now(ZoneInfo(business.timezone))
    today = now_local.date()
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id)
        .order_by(Appointment.starts_at.desc()).limit(500)).all()
    local_dates = {row.id: in_business_timezone(row.starts_at, ZoneInfo(business.timezone)).date() for row in rows}
    week = [today + timedelta(days=offset) for offset in range(7)]
    return {"business": business_json(business), "today": sum(local_dates[row.id] == today and row.status not in ("cancelled", "no_show") for row in rows),
        "upcoming": sum(local_dates[row.id] >= today and row.status == "confirmed" for row in rows),
        "checked_in": sum(row.status == "checked_in" for row in rows), "at_risk": sum(row.status == "at_risk" for row in rows),
        "weekly_counts": [sum(local_dates[row.id] == day and row.status not in ("cancelled", "no_show") for row in rows) for day in week],
        "weekly_labels": [day.strftime("%a") for day in week], "appointments": [appointment_json(db, row) for row in rows[:8]]}


@app.get("/api/admin/appointments")
def admin_appointments(business_id: int, q: str = "", status: str | None = None, service_id: int | None = None,
        staff_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
        user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    stmt = select(Appointment).where(Appointment.business_id == business.id)
    if status: stmt = stmt.where(Appointment.status == status)
    if service_id: stmt = stmt.where(Appointment.service_id == service_id)
    if staff_id: stmt = stmt.where(Appointment.staff_id == staff_id)
    if q: stmt = stmt.where(or_(Appointment.reference.ilike(f"%{q}%"), Appointment.customer_name.ilike(f"%{q}%")))
    if date_from:
        stmt = stmt.where(Appointment.starts_at >= datetime.combine(date_from, time.min, ZoneInfo(business.timezone)))
    if date_to:
        stmt = stmt.where(Appointment.starts_at < datetime.combine(date_to + timedelta(days=1), time.min, ZoneInfo(business.timezone)))
    rows = db.scalars(stmt.order_by(Appointment.starts_at.desc()).limit(100)).all()
    return [appointment_json(db, row) for row in rows]


@app.post("/api/admin/check-in")
def check_in(business_id: int, code: str = Query(..., min_length=5, max_length=128), user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == code.upper()).with_for_update())
    if not row:
        row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
            Appointment.qr_token_hash == token_hash(code)).with_for_update())
    if not row: raise HTTPException(404, "Booking code or QR pass not found")
    return appointment_json(db, check_in_appointment(db, business, row))


@app.get("/api/admin/services")
def admin_services(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    rows = db.scalars(select(Service).where(Service.business_id == business.id).order_by(Service.name, Service.id)).all()
    return [service_json(row) for row in rows]


@app.post("/api/admin/services", status_code=201)
def add_service(body: ServiceCreate, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = Service(business_id=business.id, name=body.name, description=body.description,
        duration_minutes=body.duration_minutes, buffer_minutes=body.buffer_minutes, price=body.price, active=True)
    db.add(row); db.commit(); db.refresh(row)
    return service_json(row)


@app.patch("/api/admin/services/{service_id}")
def update_service(service_id: int, body: ServiceUpdate, business_id: int,
                   user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Service).where(Service.id == service_id, Service.business_id == business.id))
    if not row: raise HTTPException(404, "Service not found")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.commit(); db.refresh(row)
    return service_json(row)


@app.get("/api/admin/staff")
def admin_staff(business_id: int, service_id: int | None = None, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    stmt = select(Staff).where(Staff.business_id == business.id)
    if service_id: stmt = stmt.join(StaffService, StaffService.staff_id == Staff.id).where(StaffService.service_id == service_id)
    rows = db.scalars(stmt.order_by(Staff.name, Staff.id)).unique().all()
    return [{"id": row.id, "business_id": business.id, "name": row.name, "title": row.title, "active": row.active,
        "service_ids": db.scalars(select(StaffService.service_id).where(StaffService.staff_id == row.id)).all()} for row in rows]


@app.post("/api/admin/staff", status_code=201)
def add_staff(body: StaffCreate, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    services = db.scalars(select(Service).where(Service.business_id == business.id, Service.id.in_(body.service_ids), Service.active.is_(True))).all() if body.service_ids else []
    if len(services) != len(set(body.service_ids)):
        raise HTTPException(400, "Every qualification must be an active service in this business")
    row = Staff(business_id=business.id, name=body.name, title=body.title, active=True)
    db.add(row); db.flush()
    for service in services: db.add(StaffService(staff_id=row.id, service_id=service.id))
    for hours in db.scalars(select(BusinessHours).where(BusinessHours.business_id == business.id)).all():
        db.add(Availability(business_id=business.id, staff_id=row.id, weekday=hours.weekday,
            start_time=hours.opens_at, end_time=hours.closes_at))
    db.commit(); db.refresh(row)
    return {"id": row.id, "business_id": business.id, "name": row.name, "title": row.title,
        "active": row.active, "service_ids": body.service_ids}


@app.patch("/api/admin/staff/{staff_id}")
def update_staff(staff_id: int, body: StaffUpdate, business_id: int,
                 user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Staff).where(Staff.id == staff_id, Staff.business_id == business.id))
    if not row: raise HTTPException(404, "Staff member not found")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.commit(); db.refresh(row)
    return {"id": row.id, "business_id": business.id, "name": row.name, "title": row.title, "active": row.active}


@app.get("/api/admin/hours")
def admin_hours(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    rows = db.scalars(select(BusinessHours).where(BusinessHours.business_id == business.id).order_by(BusinessHours.weekday)).all()
    return [{"weekday": row.weekday, "opens_at": row.opens_at.isoformat(), "closes_at": row.closes_at.isoformat()} for row in rows]


@app.put("/api/admin/hours/{weekday}")
def update_hours(weekday: int, body: HoursUpdate, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    if weekday < 0 or weekday > 6: raise HTTPException(422, "Weekday must be between 0 (Monday) and 6 (Sunday)")
    row = db.scalar(select(BusinessHours).where(BusinessHours.business_id == business.id, BusinessHours.weekday == weekday))
    if body.closed:
        if row: db.delete(row)
    else:
        if body.opens_at is None or body.closes_at is None or body.opens_at >= body.closes_at:
            raise HTTPException(422, "Provide opening and closing times, with closing after opening")
        if row:
            row.opens_at, row.closes_at = body.opens_at, body.closes_at
        else:
            row = BusinessHours(business_id=business.id, weekday=weekday, opens_at=body.opens_at, closes_at=body.closes_at)
            db.add(row)
    db.commit()
    return {"weekday": weekday, "closed": body.closed, "opens_at": body.opens_at.isoformat() if body.opens_at else None,
        "closes_at": body.closes_at.isoformat() if body.closes_at else None}


@app.get("/api/admin/waitlist")
def admin_waitlist(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    rows = db.scalars(select(WaitlistEntry).where(WaitlistEntry.business_id == business.id).order_by(WaitlistEntry.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "business_id": business.id, "service": db.get(Service, row.service_id).name,
        "name": row.customer_name, "email": row.customer_email, "date": row.preferred_date, "status": row.status} for row in rows]


@app.post("/api/admin/queue-shift/evaluate")
def evaluate_queue_shift(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    business_timezone = ZoneInfo(business.timezone)
    now = datetime.now(business_timezone)
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.status == "confirmed").with_for_update()).all()
    marked = []
    for row in rows:
        starts_at = in_business_timezone(row.starts_at, business_timezone)
        ends_at = in_business_timezone(row.ends_at, business_timezone)
        risk_at = starts_at - timedelta(minutes=max(0, business.early_arrival_minutes - business.queue_grace_minutes))
        if risk_at <= now < ends_at and row.checked_in_at is None:
            row.status = "at_risk"
            marked.append(row.reference)
    db.commit()
    return {"business_id": business.id, "marked_at_risk": marked, "policy": f"early arrival {business.early_arrival_minutes}m; grace {business.queue_grace_minutes}m; no automatic cancellation"}


@app.post("/api/admin/queue-shift/{reference}")
def queue_shift(reference: str, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.status == "confirmed").with_for_update())
    if not row: raise HTTPException(404, "Confirmed booking not found")
    db.scalar(select(Staff.id).where(Staff.id == row.staff_id, Staff.business_id == business.id).with_for_update())
    pending = db.scalar(select(SlotOffer.id).where(SlotOffer.appointment_id == row.id, SlotOffer.status == "pending"))
    if pending: raise HTTPException(409, "This booking already has an offer pending")
    advance = business.queue_shift_minutes
    business_timezone = ZoneInfo(business.timezone)
    original_start = in_business_timezone(row.starts_at, business_timezone)
    original_end = in_business_timezone(row.ends_at, business_timezone)
    proposed_start = original_start - timedelta(minutes=advance)
    proposed_end = original_end - timedelta(minutes=advance)
    if proposed_start <= datetime.now(business_timezone): raise HTTPException(409, "The suggested earlier time has already passed")
    if not is_service_slot_within_hours(db, business, row.service_id, row.staff_id, proposed_start, proposed_end):
        raise HTTPException(409, "No earlier time fits the current business hours, staff shift, service, and qualification")
    conflicts = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.staff_id == row.staff_id, Appointment.id != row.id,
        Appointment.status.in_(["confirmed", "checked_in", "in_service", "at_risk"]),
        Appointment.starts_at < proposed_end + timedelta(minutes=row.buffer_minutes),
        Appointment.ends_at > proposed_start - timedelta(minutes=business.default_buffer_minutes))).all()
    if conflicts: raise HTTPException(409, "The earlier time overlaps another appointment or buffer")
    # Both source and offered times are retained for an auditable accept/decline outcome.
    offer = SlotOffer(business_id=business.id, appointment_id=row.id, staff_id=row.staff_id,
        original_starts_at=original_start, original_ends_at=original_end, starts_at=proposed_start, ends_at=proposed_end,
        kind="queue_shift", expires_at=datetime.now(timezone.utc) + timedelta(minutes=20))
    db.add(offer)
    notify(db, business.id, row.customer_email, f"{business.name}: an earlier appointment time is available. Your current time remains reserved until you accept.")
    db.commit()
    return {"offer_id": offer.id, "status": "pending", "original_starts_at": original_start.isoformat(),
        "offered_starts_at": proposed_start.isoformat(), "business_name": business.name,
        "business_timezone": business.timezone}


@app.get("/api/offers")
def offers(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    expired = db.scalars(select(SlotOffer).join(Appointment, Appointment.id == SlotOffer.appointment_id).where(
        SlotOffer.business_id == business.id, Appointment.customer_email == user["email"],
        SlotOffer.status == "pending", SlotOffer.expires_at < datetime.now(timezone.utc))).all()
    for offer in expired:
        offer.status = "expired"
        if offer.waitlist_entry_id:
            entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
            if entry and entry.status == "offered": entry.status = "waiting"
    if expired: db.commit()
    rows = db.scalars(select(SlotOffer).join(Appointment, Appointment.id == SlotOffer.appointment_id).where(
        SlotOffer.business_id == business.id, Appointment.customer_email == user["email"],
        SlotOffer.status == "pending").order_by(SlotOffer.expires_at)).all()
    business_timezone = ZoneInfo(business.timezone)
    return [{"id": offer.id, "kind": offer.kind, "reference": db.get(Appointment, offer.appointment_id).reference,
        "business_name": business.name, "business_timezone": business.timezone,
        "original_starts_at": in_business_timezone(offer.original_starts_at, business_timezone).isoformat() if offer.original_starts_at else None,
        "starts_at": in_business_timezone(offer.starts_at, business_timezone).isoformat(),
        "expires_at": in_utc_timezone(offer.expires_at).isoformat()} for offer in rows]


@app.post("/api/offers/{offer_id}/accept")
def accept_offer(offer_id: int, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    offer = db.scalar(select(SlotOffer).where(SlotOffer.id == offer_id, SlotOffer.business_id == business.id).with_for_update())
    if not offer: raise HTTPException(404, "Offer not found")
    source = db.get(Appointment, offer.appointment_id)
    if source.customer_email != user["email"]: raise HTTPException(404, "Offer not found")
    db.scalar(select(Staff.id).where(Staff.id == offer.staff_id, Staff.business_id == business.id).with_for_update())
    now = datetime.now(timezone.utc)
    expires_at = in_utc_timezone(offer.expires_at)
    business_timezone = ZoneInfo(business.timezone)
    offered_start = in_business_timezone(offer.starts_at, business_timezone)
    offered_end = in_business_timezone(offer.ends_at, business_timezone)
    if offer.status != "pending" or expires_at < now:
        if expires_at < now:
            offer.status = "expired"
            if offer.waitlist_entry_id:
                entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
                if entry and entry.status == "offered": entry.status = "waiting"
        db.commit(); raise HTTPException(409, "Offer has expired or is no longer available")
    if offer.kind == "queue_shift":
        source_start = in_business_timezone(source.starts_at, business_timezone)
        original_start = in_business_timezone(offer.original_starts_at, business_timezone)
        if source.status != "confirmed" or source_start != original_start:
            raise HTTPException(409, "The original booking changed, so this offer is no longer available")
        if offered_start <= datetime.now(business_timezone) or not is_service_slot_within_hours(
                db, business, source.service_id, offer.staff_id, offered_start, offered_end):
            raise HTTPException(409, "That earlier time no longer fits current business or staff availability")
        conflicts = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
            Appointment.staff_id == offer.staff_id, Appointment.id != source.id,
            Appointment.status.in_(["confirmed", "checked_in", "in_service", "at_risk"]),
            Appointment.starts_at < offered_end + timedelta(minutes=source.buffer_minutes),
            Appointment.ends_at > offered_start - timedelta(minutes=business.default_buffer_minutes))).all()
        if conflicts: raise HTTPException(409, "That earlier time is no longer available")
        source.starts_at, source.ends_at = offered_start, offered_end
    else:
        if source.status != "cancelled": raise HTTPException(409, "The released appointment is no longer available")
        possible = candidate_slots(db, business, source.service_id,
            offered_start.date(), offered_start.date(), offer.staff_id)
        if not any(datetime.fromisoformat(slot["starts_at"]).astimezone(timezone.utc) == offered_start.astimezone(timezone.utc) for slot in possible):
            raise HTTPException(409, "That released time is no longer available")
        token, image = create_pass()
        service = db.get(Service, source.service_id)
        new_reference = "SS-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        source = Appointment(business_id=business.id, service_id=source.service_id, staff_id=offer.staff_id,
            customer_email=user["email"], customer_name=user["name"], reference=new_reference,
            qr_token_hash=token_hash(token), starts_at=offered_start, ends_at=offered_end,
            duration_minutes=service.duration_minutes, buffer_minutes=business.default_buffer_minutes + service.buffer_minutes,
            status="confirmed")
        db.add(source); db.flush()
        source._raw_qr, source._qr_image = token, image
        if offer.waitlist_entry_id:
            entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
            if entry: entry.status = "accepted"
    offer.status, offer.responded_at = "accepted", now
    db.commit()
    return appointment_json(db, source, include_pass=offer.kind == "waitlist")


@app.post("/api/offers/{offer_id}/decline")
def decline_offer(offer_id: int, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    offer = db.scalar(select(SlotOffer).where(SlotOffer.id == offer_id, SlotOffer.business_id == business.id).with_for_update())
    if not offer: raise HTTPException(404, "Offer not found")
    source = db.get(Appointment, offer.appointment_id)
    if source.customer_email != user["email"]: raise HTTPException(404, "Offer not found")
    if offer.status != "pending": raise HTTPException(409, "Offer is no longer available")
    offer.status, offer.responded_at = "declined", datetime.now(timezone.utc)
    if offer.waitlist_entry_id:
        entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
        if entry and entry.status == "offered": entry.status = "declined"
    db.commit()
    return {"status": "declined", "original_starts_at": offer.original_starts_at.isoformat() if offer.original_starts_at else None}


@app.post("/api/admin/appointments/{reference}/mark-no-show")
def mark_no_show(reference: str, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id, Appointment.reference == reference).with_for_update())
    if not row or row.status != "at_risk": raise HTTPException(409, "Only an At Risk appointment can be reviewed")
    business_timezone = ZoneInfo(business.timezone)
    allowed_at = in_business_timezone(row.starts_at, business_timezone) + timedelta(minutes=business.queue_grace_minutes)
    if datetime.now(business_timezone) < allowed_at: raise HTTPException(409, "No-show review opens after the appointment start and configured grace period")
    row.status = "no_show"
    db.commit()
    return appointment_json(db, row)


@app.get("/api/admin/settings")
def admin_settings(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    return {**business_json(business), "default_buffer_minutes": business.default_buffer_minutes,
        "check_in_minutes": business.check_in_minutes, "early_arrival_minutes": business.early_arrival_minutes,
        "queue_grace_minutes": business.queue_grace_minutes, "queue_shift_minutes": business.queue_shift_minutes,
        "cancellation_cutoff_hours": business.cancellation_cutoff_hours, "notifications": "Simulated in-app"}
