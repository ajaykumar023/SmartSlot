from datetime import date, datetime, time, timedelta, timezone
from contextlib import asynccontextmanager, suppress
import asyncio
import os
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
from .models import Appointment, Availability, Business, BusinessHours, CustomerArrival, Notification, Service, SlotOffer, Staff, StaffPresence, StaffService, WaitlistEntry, AdminAlert
from .qr import create_pass, token_hash
from .schemas import ArrivalUpdate, BookingCreate, CodeScan, DemoLogin, HoursUpdate, PresenceUpdate, ServiceCreate, ServiceUpdate, StaffCreate, StaffUpdate, WaitlistCreate, DelayRequest, SimulationRequest, GeoSimulationRequest, AutoBookRequest
from .scheduling import business_json, candidate_slots
from .waitlist import expire_offers, match_waitlist, notify, offer_recipient
from .queue_engine import available_for_shift, shift_recommendations, delay_recommendations, utc
from .simulation import simulate
from .geo_simulation import simulate_geo_reroute
from .auto_allocator import process_business
from .automation_runtime import sweep_forever
from .geosmart_api import router as geosmart_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(sweep_forever()) if settings.auto_allocator_enabled and not os.environ.get("PYTEST_CURRENT_TEST") else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="SmartSlot API", version="2.2.0", description="Multi-industry appointment booking and check-in.", lifespan=lifespan)
app.include_router(geosmart_router)
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


def appointment_json(db: Session, item: Appointment, include_pass: bool = False) -> dict:
    service = db.get(Service, item.service_id)
    staff = db.get(Staff, item.staff_id)
    business = db.get(Business, item.business_id)
    result = {"id": item.id, "reference": item.reference, "business_id": item.business_id,
        "business_name": business.name, "business_category": business.category,
        "business_timezone": business.timezone, "service_id": item.service_id,
        "service_name": service.name if service else "Service unavailable",
        "staff_id": item.staff_id, "staff_name": staff.name if staff else "Unassigned",
        "staff_title": staff.title if staff else "Staff member", "customer_name": item.customer_name,
        "customer_email": item.customer_email, "starts_at": utc(item.starts_at).isoformat(),
        "ends_at": utc(item.ends_at).isoformat(), "duration_minutes": item.duration_minutes,
        "buffer_minutes": item.buffer_minutes, "status": item.status}
    if include_pass:
        result["qr_token"] = getattr(item, "_raw_qr", None)
        result["qr_image"] = getattr(item, "_qr_image", None)
    return result


def pass_day_ready(item: Appointment, business: Business) -> bool:
    """Real QR credentials can only be delivered from midnight on the business's appointment day."""
    now = datetime.now(timezone.utc)
    tz = ZoneInfo(business.timezone)
    return (item.status in ("confirmed", "at_risk") and
            now < utc(item.ends_at) and
            now.astimezone(tz).date() >= utc(item.starts_at).astimezone(tz).date())


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
    return appointment_json(db, row, include_pass=pass_day_ready(row, business))


@app.post("/api/appointments/auto-book", status_code=201)
def auto_book(body: AutoBookRequest, business_id: int,
              user=Depends(current_user), db: Session = Depends(get_db)):
    """Deterministic earliest feasible appointment with qualified staff.

    Balances same-time qualified staff by existing workload; a DB lock and the
    normal booking endpoint recheck eliminate race conditions in PostgreSQL.
    """
    require_customer(user)
    business = scope_business(db, user, business_id)
    if body.email.lower() != user["email"]:
        raise HTTPException(403, "Use your signed-in email")
    local_today = datetime.now(ZoneInfo(business.timezone)).date()
    if body.preferred_date < local_today or body.preferred_date > local_today + timedelta(days=30):
        raise HTTPException(422, "Choose a date within the next 30 days")
    slots = candidate_slots(db, business, body.service_id, body.preferred_date, body.preferred_date)
    if not slots:
        raise HTTPException(409, "No available slot for this service and date; try the waitlist")
    active = db.scalars(select(Appointment).where(Appointment.business_id==business.id,
        Appointment.status.in_(("confirmed", "checked_in", "at_risk")))).all()
    workload = {}
    for a in active:
        workload[a.staff_id] = workload.get(a.staff_id,0) + 1
    presence = {p.staff_id:p.status for p in db.scalars(select(StaffPresence).where(StaffPresence.business_id==business.id)).all()}
    eligible = [s for s in slots if presence.get(s["staff_id"],"on_site") not in ("away","break")]
    if not eligible:
        raise HTTPException(409, "All qualified staff are currently reported unavailable")
    chosen=min(eligible,key=lambda slot:(datetime.fromisoformat(slot["starts_at"]).astimezone(timezone.utc),
                                        workload.get(slot["staff_id"],0), slot["staff_id"]))
    result = create_appointment(BookingCreate(service_id=body.service_id,starts_at=datetime.fromisoformat(chosen["starts_at"]),
            name=body.name,email=body.email,staff_id=chosen["staff_id"]),business_id,user,db)
    db.add(AdminAlert(business_id=business.id,kind="auto_booking",reference=result["reference"],
        message=f"Smart allocation: {body.name} automatically booked with {chosen['staff_name']} at {result['starts_at']}."))
    db.commit()
    result["allocation"]={"mode":"automatic", "strategy":"earliest feasible time, then lowest staff workload",
        "reason":f"Assigned {chosen['staff_name']} for earliest suitable appointment; existing bookings are protected.",
        "not_ml":True}
    return result


@app.get("/api/appointments/{reference}/qr/status")
def qr_day_status(reference: str, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    """Read-only check-in pass readiness. Uses the business timezone, not the device clock."""
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]))
    if not row:
        raise HTTPException(404, "Booking not found")
    tz = ZoneInfo(business.timezone)
    now = datetime.now(timezone.utc)
    opening_day = utc(row.starts_at).astimezone(tz).date()
    opens_at = datetime.combine(opening_day, time.min, tz).astimezone(timezone.utc)
    check_in_opens_at = utc(row.starts_at) - timedelta(minutes=business.check_in_minutes)
    active = row.status in ("confirmed", "at_risk") and now < utc(row.ends_at)
    ready = active and now >= opens_at
    return {"reference": row.reference, "available": ready,
            "status": row.status, "business_timezone": business.timezone,
            "opens_at": opens_at.isoformat(),
            "check_in_opens_at": check_in_opens_at.isoformat(),
            "appointment_at": utc(row.starts_at).isoformat(),
            "reason": "ready" if ready else "scheduled" if active else "inactive"}


@app.post("/api/appointments/{reference}/qr/activate")
def activate_day_pass(reference: str, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    """Issue a QR only on appointment day. Rotates old hash; old printed passes cease to work."""
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]).with_for_update())
    if not row:
        raise HTTPException(404, "Booking not found")
    now = datetime.now(timezone.utc)
    if row.status not in ("confirmed", "at_risk") or now >= utc(row.ends_at):
        raise HTTPException(409, "Pass unavailable for an inactive or ended appointment")
    tz = ZoneInfo(business.timezone)
    if now.astimezone(tz).date() < utc(row.starts_at).astimezone(tz).date():
        raise HTTPException(409, "Your QR pass opens on the day of your appointment")
    token, image = create_pass()
    row.qr_token_hash = token_hash(token)
    db.commit()
    row._raw_qr, row._qr_image = token, image
    return appointment_json(db, row, include_pass=True)


@app.post("/api/appointments/{reference}/qr/reissue")
def reissue_qr(reference: str, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    """Rotate a lost QR pass: the old secret immediately becomes unusable."""
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]).with_for_update())
    if not row: raise HTTPException(404, "Booking not found")
    if row.status not in ("confirmed", "at_risk") or utc(row.ends_at) <= datetime.now(timezone.utc):
        raise HTTPException(409, "Cannot reissue a pass for an inactive or ended appointment")
    if not pass_day_ready(row, business):
        raise HTTPException(409, "Your QR pass opens on the day of your appointment")
    token, image = create_pass()
    row.qr_token_hash = token_hash(token)
    db.commit()
    row._raw_qr, row._qr_image = token, image
    return appointment_json(db, row, include_pass=True)


@app.get("/api/appointments/mine")
def my_appointments(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.customer_email == user["email"]).order_by(Appointment.starts_at.desc()).limit(100)).all()
    return [appointment_json(db, row) for row in rows]


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
    if row.status != "confirmed" or utc(row.starts_at) <= datetime.now(timezone.utc) + timedelta(hours=business.cancellation_cutoff_hours):
        raise HTTPException(409, f"Bookings can be cancelled up to {business.cancellation_cutoff_hours} hours before the start time")
    row.status = "cancelled"
    # Any pending queue-shift offer is invalid after cancellation.
    for offer in db.scalars(select(SlotOffer).where(SlotOffer.appointment_id == row.id,
            SlotOffer.kind == "queue_shift", SlotOffer.status == "pending")).all():
        offer.status = "expired"
    db.flush()
    db.scalar(select(Staff.id).where(Staff.id == row.staff_id, Staff.business_id == business.id).with_for_update())
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
    today = datetime.now(ZoneInfo(business.timezone)).date()
    if body.preferred_date < today:
        raise HTTPException(422, "Waitlist date cannot be in the past")
    duplicate = db.scalar(select(WaitlistEntry.id).where(WaitlistEntry.business_id == business.id,
        WaitlistEntry.service_id == service.id, WaitlistEntry.customer_email == user["email"],
        WaitlistEntry.preferred_date == body.preferred_date.isoformat(),
        WaitlistEntry.status.in_(["waiting", "offered"])))
    if duplicate:
        raise HTTPException(409, "You are already waiting for this service on that date")
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


@app.get("/api/waitlist/mine")
def my_waitlist(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    rows = db.scalars(select(WaitlistEntry).where(WaitlistEntry.business_id == business.id,
        WaitlistEntry.customer_email == user["email"]).order_by(WaitlistEntry.created_at.desc())).all()
    return [{"id": r.id, "service_id": r.service_id, "preferred_date": r.preferred_date,
        "status": r.status, "created_at": r.created_at.isoformat()} for r in rows]


@app.post("/api/waitlist/{entry_id}/withdraw")
def withdraw_waitlist(entry_id: int, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == entry_id,
        WaitlistEntry.business_id == business.id, WaitlistEntry.customer_email == user["email"]).with_for_update())
    if not entry: raise HTTPException(404, "Waitlist entry not found")
    if entry.status not in ("waiting", "offered"):
        raise HTTPException(409, "This waitlist entry can no longer be withdrawn")
    old_offer = db.scalar(select(SlotOffer).where(SlotOffer.waitlist_entry_id == entry.id,
        SlotOffer.status == "pending").with_for_update())
    entry.status = "withdrawn"
    if old_offer:
        old_offer.status, old_offer.responded_at = "declined", datetime.now(timezone.utc)
        db.flush()
        source = db.get(Appointment, old_offer.appointment_id)
        if source: match_waitlist(db, source, business)
    db.commit()
    return {"status": "withdrawn", "waitlist_id": entry.id}


@app.post("/api/appointments/{reference}/arrival")
def report_arrival(reference: str, body: ArrivalUpdate, business_id: int,
                   user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]).with_for_update())
    if not row: raise HTTPException(404, "Booking not found")
    if row.status not in ("confirmed", "at_risk", "checked_in"):
        raise HTTPException(409, "Arrival updates are only available for active bookings")
    if utc(row.ends_at) < datetime.now(timezone.utc):
        raise HTTPException(409, "This appointment has ended")
    if body.status == "on_the_way" and body.eta_minutes is None:
        raise HTTPException(422, "Please provide your estimated travel time")
    if row.status == "checked_in" and body.status != "arrived":
        raise HTTPException(409, "Already checked in")
    arrival = db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id == row.id))
    if not arrival:
        arrival = CustomerArrival(appointment_id=row.id)
        db.add(arrival)
    arrival.status = body.status
    arrival.eta_minutes = body.eta_minutes if body.status == "on_the_way" else 0
    arrival.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"reference": row.reference, "status": arrival.status, "eta_minutes": arrival.eta_minutes,
        "checked_in": row.status == "checked_in", "verified": False,
        "note": "Self-reported arrival is not a verified check-in."}


@app.get("/api/queue/mine")
def my_queue(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    now = datetime.now(timezone.utc)
    bookings = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.customer_email == user["email"], Appointment.status.in_(["confirmed", "checked_in", "at_risk"]))).all()
    result = []
    for row in bookings:
        if utc(row.ends_at) <= now: continue
        ahead = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
            Appointment.staff_id == row.staff_id, Appointment.id != row.id,
            Appointment.status.in_(["confirmed", "checked_in", "at_risk"]))).all()
        ahead_count = sum(utc(a.starts_at) <= utc(row.starts_at) and utc(a.ends_at) > now for a in ahead)
        arrival = db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id == row.id))
        result.append({"reference": row.reference, "starts_at": utc(row.starts_at).isoformat(),
            "staff_id": row.staff_id, "queue_position": ahead_count + 1,
            "people_ahead": ahead_count, "status": row.status,
            "arrival_status": arrival.status if arrival else "not_reported",
            "eta_minutes": arrival.eta_minutes if arrival else None,
            "note": "Estimated position among this staff member's active bookings; not a guaranteed start time."})
    return result


@app.get("/api/admin/dashboard")
def dashboard(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    now_local = datetime.now(ZoneInfo(business.timezone))
    today = now_local.date()
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id)
        .order_by(Appointment.starts_at.desc()).limit(500)).all()
    local_dates = {row.id: row.starts_at.astimezone(ZoneInfo(business.timezone)).date() for row in rows}
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


def _check_in_validation(db: Session, business: Business, code: str, lock: bool = False):
    query = select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == code.strip().upper())
    if lock: query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        query = select(Appointment).where(Appointment.business_id == business.id,
            Appointment.qr_token_hash == token_hash(code.strip()))
        if lock: query = query.with_for_update()
        row = db.scalar(query)
    if not row:
        raise HTTPException(404, "Booking code or QR pass not found for this business")
    if row.status not in ("confirmed", "at_risk"):
        raise HTTPException(409, f"Cannot check in a {row.status} booking")
    now = datetime.now(timezone.utc)
    if utc(row.starts_at) > now + timedelta(minutes=business.check_in_minutes):
        raise HTTPException(409, f"Check-in opens {business.check_in_minutes} minutes before the appointment")
    if utc(row.ends_at) < now:
        raise HTTPException(409, "This appointment has ended")
    return row


@app.get("/api/admin/check-in/validate")
def validate_check_in(business_id: int, code: str = Query(..., min_length=5, max_length=128),
                      user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = _check_in_validation(db, business, code)
    return {"valid": True, "reference": row.reference, "customer_name": row.customer_name,
        "starts_at": utc(row.starts_at).isoformat(), "status": row.status,
        "note": "Preview only. Use POST /api/admin/check-in to confirm."}


@app.post("/api/admin/check-in")
def check_in(business_id: int, code: str = Query(..., min_length=5, max_length=128),
             user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = _check_in_validation(db, business, code, lock=True)
    row.status, row.checked_in_at = "checked_in", datetime.now(timezone.utc)
    arrival = db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id == row.id))
    if arrival:
        arrival.status, arrival.eta_minutes, arrival.updated_at = "arrived", 0, datetime.now(timezone.utc)
    db.commit()
    return appointment_json(db, row)


@app.post("/api/admin/check-in/preview")
def secure_preview_check_in(body: CodeScan, business_id: int,
                            user=Depends(admin_user), db: Session = Depends(get_db)):
    """Recommended scanner API: bearer QR secret stays in JSON body, not a URL."""
    business = scope_business(db, user, business_id, require_admin=True)
    row = _check_in_validation(db, business, body.code)
    service = db.get(Service, row.service_id)
    staff = db.get(Staff, row.staff_id)
    return {"valid": True, "reference": row.reference, "customer_name": row.customer_name,
        "starts_at": utc(row.starts_at).isoformat(), "ends_at": utc(row.ends_at).isoformat(),
        "service_name": service.name if service else "Service unavailable",
        "staff_name": staff.name if staff else "Unassigned", "status": row.status,
        "note": "Preview only; call POST /api/admin/check-in/confirm to complete."}


@app.post("/api/admin/check-in/confirm")
def secure_confirm_check_in(body: CodeScan, business_id: int,
                            user=Depends(admin_user), db: Session = Depends(get_db)):
    """Recommended check-in API. The historical query-string endpoint remains for old UIs."""
    business = scope_business(db, user, business_id, require_admin=True)
    row = _check_in_validation(db, business, body.code, lock=True)
    row.status, row.checked_in_at = "checked_in", datetime.now(timezone.utc)
    arrival = db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id == row.id))
    if arrival:
        arrival.status, arrival.eta_minutes, arrival.updated_at = "arrived", 0, datetime.now(timezone.utc)
    db.commit()
    return appointment_json(db, row)


@app.get("/api/admin/services")
def admin_services(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    rows = db.scalars(select(Service).where(Service.business_id == business.id).order_by(Service.name, Service.id)).all()
    return [service_json(row) for row in rows]


@app.post("/api/admin/services", status_code=201)
def add_service(body: ServiceCreate, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = Service(business_id=business.id, name=body.name, description=body.description,
        duration_minutes=body.duration_minutes, buffer_minutes=body.buffer_minutes, active=True)
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


@app.post("/api/admin/automation/run")
def admin_run_allocator(business_id:int,user=Depends(admin_user),db:Session=Depends(get_db)):
    business=scope_business(db,user,business_id,require_admin=True)
    result=process_business(db,business)
    db.commit()
    return result


@app.post("/api/admin/queue-shift/evaluate")
def evaluate_queue_shift(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.status == "confirmed").with_for_update()).all()
    marked, eta_alerts, absent_staff = [], [], []
    presence = {p.staff_id: p for p in db.scalars(select(StaffPresence).where(StaffPresence.business_id == business.id)).all()}
    for row in rows:
        # A customer is not a no-show until appointment start PLUS grace period.
        if utc(row.starts_at) + timedelta(minutes=business.queue_grace_minutes) <= now < utc(row.ends_at) and row.checked_in_at is None:
            row.status = "at_risk"
            marked.append(row.reference)
        arrival = db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id == row.id))
        if (arrival and arrival.status == "on_the_way" and
            utc(arrival.updated_at) + timedelta(minutes=arrival.eta_minutes or 0) >
            utc(row.starts_at) + timedelta(minutes=business.queue_grace_minutes)):
            eta_alerts.append(row.reference)
        if row.staff_id in presence and presence[row.staff_id].status != "on_site":
            absent_staff.append(row.staff_id)
    db.commit()
    return {"business_id": business.id, "marked_at_risk": marked,
        "customer_eta_alerts": eta_alerts, "staff_unavailable_ids": sorted(set(absent_staff)),
        "policy": f"no-show only after start + {business.queue_grace_minutes} minute grace; staff presence and ETA are simulated/self-reported; no automatic cancellation"}


@app.get("/api/admin/queue/overview")
def admin_queue_overview(business_id: int, date_on: date | None = None,
                         user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    local_today = datetime.now(ZoneInfo(business.timezone)).date()
    day = date_on or local_today
    if abs((day - local_today).days) > 31:
        raise HTTPException(422, "Choose a date within 31 days")
    local_start = datetime.combine(day, time.min, ZoneInfo(business.timezone))
    local_end = local_start + timedelta(days=1)
    bookings = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.starts_at >= local_start, Appointment.starts_at < local_end).order_by(Appointment.staff_id, Appointment.starts_at)).all()
    staff_rows = db.scalars(select(Staff).where(Staff.business_id == business.id)).all()
    result = []
    for person in staff_rows:
        presence = db.scalar(select(StaffPresence).where(StaffPresence.business_id == business.id,
            StaffPresence.staff_id == person.id))
        appointments = []
        for row in bookings:
            if row.staff_id != person.id: continue
            arrival = db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id == row.id))
            appointments.append({"reference": row.reference, "customer_name": row.customer_name,
                "starts_at": utc(row.starts_at).isoformat(), "status": row.status,
                "arrival_status": arrival.status if arrival else "not_reported",
                "eta_minutes": arrival.eta_minutes if arrival else None,
                "service_id": row.service_id, "duration_minutes": row.duration_minutes})
        result.append({"staff_id": person.id, "staff_name": person.name,
            "presence": presence.status if presence else "unreported",
            "presence_source": presence.source if presence else None,
            "appointments": appointments})
    return {"date": day.isoformat(), "business_id": business.id,
        "staff_queues": result, "source": "demo booking records and unverified manual/ETA signals"}


@app.get("/api/admin/queue/recommendations")
def queue_recommendations(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.status == "confirmed", Appointment.starts_at > now,
        Appointment.starts_at < now + timedelta(days=2)).order_by(Appointment.starts_at).limit(100)).all()
    results = []
    for row in rows:
        slots = shift_recommendations(db, business, row, now=now)
        if slots:
            results.append({"reference": row.reference, "customer_name": row.customer_name,
                "current_starts_at": utc(row.starts_at).isoformat(), "staff_id": row.staff_id,
                "suggestions": slots})
    return {"strategy": "deterministic earliest-feasible slot, subject to customer acceptance", "recommendations": results}


@app.post("/api/admin/queue-shift/{reference}")
def queue_shift(reference: str, business_id: int,
                advance_minutes: int | None = Query(default=None, ge=5, le=120),
                user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.status == "confirmed").with_for_update())
    if not row: raise HTTPException(404, "Confirmed booking not found")
    db.scalar(select(Staff.id).where(Staff.id == row.staff_id, Staff.business_id == business.id).with_for_update())
    pending = db.scalar(select(SlotOffer.id).where(SlotOffer.appointment_id == row.id,
        SlotOffer.kind.in_(("queue_shift", "delay_shift")), SlotOffer.status == "pending", SlotOffer.expires_at > datetime.now(timezone.utc)))
    if pending: raise HTTPException(409, "This booking already has an offer pending")
    advance = business.queue_shift_minutes if advance_minutes is None else advance_minutes
    proposed_start = utc(row.starts_at) - timedelta(minutes=advance)
    proposed_end = utc(row.ends_at) - timedelta(minutes=advance)
    ok, reason = available_for_shift(db, business, row, proposed_start, proposed_end)
    if not ok: raise HTTPException(409, f"Earlier time is unavailable: {reason}")
    offer = SlotOffer(business_id=business.id, appointment_id=row.id, staff_id=row.staff_id,
        original_starts_at=row.starts_at, original_ends_at=row.ends_at, starts_at=proposed_start, ends_at=proposed_end,
        kind="queue_shift", expires_at=datetime.now(timezone.utc) + timedelta(minutes=20))
    db.add(offer)
    notify(db, business.id, row.customer_email, f"{business.name}: an earlier time is available. Your original slot remains booked until you accept.")
    db.commit()
    return {"offer_id": offer.id, "status": "pending", "original_starts_at": utc(offer.original_starts_at).isoformat(),
        "offered_starts_at": utc(offer.starts_at).isoformat(), "business_name": business.name,
        "reason": reason, "requires_acceptance": True}


@app.post("/api/appointments/{reference}/delay-options")
def customer_delay_options(reference: str, body: DelayRequest, business_id: int,
                           user=Depends(current_user), db: Session = Depends(get_db)):
    """Show up to 30-minute delay options; self-reported ETA, not live GPS."""
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]))
    if not row: raise HTTPException(404, "Booking not found")
    options = delay_recommendations(db, business, row, body.eta_minutes, body.max_delay_minutes)
    return {"reference": row.reference, "original_starts_at": utc(row.starts_at).isoformat(),
        "options": options, "eta_source": "customer_reported", "max_delay_minutes": body.max_delay_minutes,
        "note": "Preview only. Other customers are never displaced, and the original booking stays reserved."}


@app.post("/api/appointments/{reference}/delay-request")
def customer_delay_request(reference: str, body: DelayRequest, business_id: int,
                           user=Depends(current_user), db: Session = Depends(get_db)):
    """Make a time-limited offer to the booking owner; no mutation to booking time yet."""
    require_customer(user)
    business = scope_business(db, user, business_id)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id,
        Appointment.reference == reference, Appointment.customer_email == user["email"]).with_for_update())
    if not row: raise HTTPException(404, "Booking not found")
    db.scalar(select(Staff.id).where(Staff.id == row.staff_id,
        Staff.business_id == business.id).with_for_update())
    now = datetime.now(timezone.utc)
    pending = db.scalar(select(SlotOffer.id).where(SlotOffer.appointment_id == row.id,
        SlotOffer.kind.in_(("queue_shift", "delay_shift")), SlotOffer.status == "pending",
        SlotOffer.expires_at > now))
    if pending: raise HTTPException(409, "An appointment change offer is already pending")
    options = delay_recommendations(db, business, row, body.eta_minutes, body.max_delay_minutes, now)
    if not options:
        raise HTTPException(409, "No reachable and available later appointment within the configured delay cap")
    choice = options[0]
    offer = SlotOffer(business_id=business.id, appointment_id=row.id, staff_id=row.staff_id,
        original_starts_at=row.starts_at, original_ends_at=row.ends_at,
        starts_at=datetime.fromisoformat(choice["starts_at"]),
        ends_at=datetime.fromisoformat(choice["ends_at"]), kind="delay_shift",
        expires_at=now + timedelta(minutes=5))
    db.add(offer)
    notify(db, business.id, row.customer_email,
        f"A later appointment at {choice['starts_at']} is offered for five minutes; please confirm. Your original booking remains reserved.")
    db.commit()
    return {"offer_id": offer.id, "status": "pending", "kind": "delay_shift",
        "original_starts_at": utc(offer.original_starts_at).isoformat(),
        "offered_starts_at": utc(offer.starts_at).isoformat(),
        "expires_at": utc(offer.expires_at).isoformat(), "requires_acceptance": True,
        "eta_source": "customer_reported"}


@app.post("/api/admin/simulation/limited-delay")
def admin_limited_delay_simulation(body: SimulationRequest, business_id: int,
                                   user=Depends(admin_user), db: Session = Depends(get_db)):
    """Pure what-if simulation; never accesses or edits real appointments."""
    scope_business(db, user, business_id, require_admin=True)
    return simulate(body.scenario, body.traffic_delay_minutes,
                    body.max_delay_minutes, body.action)


@app.post("/api/admin/simulation/geo-reroute")
def admin_geo_reroute_simulation(body: GeoSimulationRequest, business_id: int,
                                 user=Depends(admin_user), db: Session = Depends(get_db)):
    """Admin-only fictional cross-branch rerouting; NEVER writes appointments."""
    scope_business(db, user, business_id, require_admin=True)
    return simulate_geo_reroute(body.scenario, body.traffic_delay_minutes,
                                body.max_delay_minutes, body.auto_reroute_opt_in)


@app.post("/api/admin/offers/expire")
def admin_expire_offers(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    expired = expire_offers(db, business)
    db.commit()
    return {"expired_offer_ids": expired, "count": len(expired), "reoffered_automatically": True}


@app.post("/api/admin/staff/{staff_id}/presence")
def update_staff_presence(staff_id: int, body: PresenceUpdate, business_id: int,
                          user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    person = db.scalar(select(Staff).where(Staff.id == staff_id, Staff.business_id == business.id).with_for_update())
    if not person: raise HTTPException(404, "Staff member not found")
    row = db.scalar(select(StaffPresence).where(StaffPresence.business_id == business.id,
        StaffPresence.staff_id == staff_id))
    if not row:
        row = StaffPresence(business_id=business.id, staff_id=staff_id)
        db.add(row)
    row.status, row.updated_at = body.status, datetime.now(timezone.utc)
    db.commit()
    return {"staff_id": staff_id, "status": body.status, "source": "admin_demo",
        "note": "This is manually entered, not verified RFID or biometric attendance."}


@app.get("/api/offers")
def offers(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    expire_offers(db, business)
    db.commit()
    # Waitlist offers are linked to the waitlist entry, not the cancelled customer.
    customer_waitlist = select(WaitlistEntry.id).where(WaitlistEntry.business_id == business.id,
        WaitlistEntry.customer_email == user["email"])
    my_bookings = select(Appointment.id).where(Appointment.business_id == business.id,
        Appointment.customer_email == user["email"])
    rows = db.scalars(select(SlotOffer).where(SlotOffer.business_id == business.id,
        SlotOffer.status == "pending", SlotOffer.expires_at > datetime.now(timezone.utc),
        or_(SlotOffer.waitlist_entry_id.in_(customer_waitlist),
            (SlotOffer.waitlist_entry_id.is_(None) & SlotOffer.appointment_id.in_(my_bookings)))).order_by(SlotOffer.expires_at)).all()
    return [{"id": offer.id, "kind": offer.kind,
        "reference": db.get(Appointment, offer.appointment_id).reference if offer.kind in ("queue_shift", "delay_shift") else None,
        "business_name": business.name, "business_timezone": business.timezone,
        "original_starts_at": utc(offer.original_starts_at).isoformat() if offer.original_starts_at else None,
        "starts_at": utc(offer.starts_at).isoformat(), "expires_at": utc(offer.expires_at).isoformat()} for offer in rows]


@app.post("/api/offers/{offer_id}/accept")
def accept_offer(offer_id: int, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    offer = db.scalar(select(SlotOffer).where(SlotOffer.id == offer_id, SlotOffer.business_id == business.id).with_for_update())
    if not offer: raise HTTPException(404, "Offer not found")
    if offer_recipient(db, offer) != user["email"]: raise HTTPException(404, "Offer not found")
    source = db.get(Appointment, offer.appointment_id)
    db.scalar(select(Staff.id).where(Staff.id == offer.staff_id, Staff.business_id == business.id).with_for_update())
    now = datetime.now(timezone.utc)
    if offer.status != "pending" or utc(offer.expires_at) <= now:
        if utc(offer.expires_at) <= now:
            offer.status = "expired"
            if offer.waitlist_entry_id:
                entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
                if entry and entry.status == "offered": entry.status = "waiting"
        db.commit(); raise HTTPException(409, "Offer has expired or is no longer available")
    if offer.kind in ("queue_shift", "delay_shift"):
        if source.status != "confirmed" or utc(source.starts_at) != utc(offer.original_starts_at):
            raise HTTPException(409, "The original booking changed, so this offer is no longer available")
        ok, reason = available_for_shift(db, business, source, offer.starts_at, offer.ends_at, ignore_offer_id=offer.id, now=now)
        if not ok: raise HTTPException(409, f"The proposed time is no longer available: {reason}")
        source.starts_at, source.ends_at = offer.starts_at, offer.ends_at
    else:
        if source.status not in ("cancelled", "no_show"): raise HTTPException(409, "The released appointment is no longer available")
        possible = candidate_slots(db, business, source.service_id,
            utc(offer.starts_at).astimezone(ZoneInfo(business.timezone)).date(),
            utc(offer.starts_at).astimezone(ZoneInfo(business.timezone)).date(), offer.staff_id, exclude_offer_id=offer.id)
        if not any(utc(datetime.fromisoformat(slot["starts_at"])) == utc(offer.starts_at) for slot in possible):
            raise HTTPException(409, "That released time is no longer available")
        token, image = create_pass()
        service = db.get(Service, source.service_id)
        new_reference = "SS-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        source = Appointment(business_id=business.id, service_id=source.service_id, staff_id=offer.staff_id,
            customer_email=user["email"], customer_name=user["name"], reference=new_reference,
            qr_token_hash=token_hash(token), starts_at=offer.starts_at, ends_at=offer.ends_at,
            duration_minutes=service.duration_minutes, buffer_minutes=business.default_buffer_minutes + service.buffer_minutes,
            status="confirmed")
        db.add(source); db.flush()
        source._raw_qr, source._qr_image = token, image
        if offer.waitlist_entry_id:
            entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
            if entry: entry.status = "accepted"
    offer.status, offer.responded_at = "accepted", now
    db.commit()
    return appointment_json(db, source, include_pass=offer.kind == "waitlist" and pass_day_ready(source, business))


@app.post("/api/offers/{offer_id}/decline")
def decline_offer(offer_id: int, business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_customer(user)
    business = scope_business(db, user, business_id)
    offer = db.scalar(select(SlotOffer).where(SlotOffer.id == offer_id, SlotOffer.business_id == business.id).with_for_update())
    if not offer: raise HTTPException(404, "Offer not found")
    if offer_recipient(db, offer) != user["email"]: raise HTTPException(404, "Offer not found")
    source = db.get(Appointment, offer.appointment_id)
    if offer.status != "pending" or utc(offer.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(409, "Offer is no longer available")
    offer.status, offer.responded_at = "declined", datetime.now(timezone.utc)
    if offer.waitlist_entry_id:
        entry = db.get(WaitlistEntry, offer.waitlist_entry_id)
        if entry and entry.status == "offered": entry.status = "waiting"
        db.flush()
        if source.status in ("cancelled", "no_show"):
            match_waitlist(db, source, business)
    db.commit()
    return {"status": "declined", "original_starts_at": offer.original_starts_at.isoformat() if offer.original_starts_at else None}


@app.post("/api/admin/appointments/{reference}/mark-no-show")
def mark_no_show(reference: str, business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    row = db.scalar(select(Appointment).where(Appointment.business_id == business.id, Appointment.reference == reference).with_for_update())
    if not row or row.status != "at_risk": raise HTTPException(409, "Only an At Risk appointment can be reviewed")
    allowed_at = utc(row.starts_at) + timedelta(minutes=business.queue_grace_minutes)
    if datetime.now(timezone.utc) < allowed_at: raise HTTPException(409, "No-show review opens after the appointment start and configured grace period")
    row.status = "no_show"
    db.flush()
    # A past no-show slot cannot be resold; only genuinely future released capacity is matchable.
    match_waitlist(db, row, business)
    db.commit()
    return appointment_json(db, row)


@app.get("/api/admin/settings")
def admin_settings(business_id: int, user=Depends(admin_user), db: Session = Depends(get_db)):
    business = scope_business(db, user, business_id, require_admin=True)
    return {**business_json(business), "default_buffer_minutes": business.default_buffer_minutes,
        "check_in_minutes": business.check_in_minutes, "early_arrival_minutes": business.early_arrival_minutes,
        "queue_grace_minutes": business.queue_grace_minutes, "queue_shift_minutes": business.queue_shift_minutes,
        "cancellation_cutoff_hours": business.cancellation_cutoff_hours, "notifications": "Simulated in-app"}
