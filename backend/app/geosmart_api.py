"""GPS + admin alert endpoints; mounted on the main FastAPI app."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import admin_user, current_user
from .config import settings
from .database import get_db
from .georoutes import RoutingUnavailable, estimate_travel
from .models import AdminAlert, Appointment, Business, CustomerArrival, Notification
from .queue_engine import utc
from .schemas import LocationUpdate, TravelLocation
from .waitlist import notify

router = APIRouter(prefix="/api")


def scoped(db: Session, user: dict, business_id: int, admin: bool=False):
    business=db.get(Business,business_id)
    if not business or not business.active:
        raise HTTPException(404,"Business not found")
    if admin:
        if user.get("role")!="admin" or business_id not in user.get("business_ids",[]):
            raise HTTPException(403,"Admin access required")
    elif user.get("role")!="customer" or user.get("business_id")!=business_id:
        raise HTTPException(403,"Customer access required")
    return business


@router.get("/businesses/{business_id}/location")
def public_location(business_id:int, db:Session=Depends(get_db)):
    business=db.get(Business,business_id)
    if not business or not business.active: raise HTTPException(404,"Business not found")
    return {"business_id":business.id,"name":business.name,"latitude":business.latitude,"longitude":business.longitude,
            "configured":business.latitude is not None and business.longitude is not None}


@router.put("/admin/location")
def set_location(body:LocationUpdate,business_id:int,user=Depends(admin_user),db:Session=Depends(get_db)):
    business=scoped(db,user,business_id,admin=True)
    business.latitude, business.longitude=body.latitude,body.longitude
    db.commit()
    return {"business_id":business.id,"latitude":business.latitude,"longitude":business.longitude}


@router.get("/travel/provider-status")
def travel_provider_status(business_id: int, user=Depends(current_user), db: Session=Depends(get_db)):
    # The client only needs configuration status, never a server-side API key.
    scoped(db, user, business_id)
    return {"provider": "tomtom", "routes_configured": bool(settings.tomtom_routing_api_key.strip()),
            "traffic_aware": True, "demo_mode": False}


@router.post("/appointments/{reference}/travel-eta")
def travel_eta(reference:str,body:TravelLocation,business_id:int,
               user=Depends(current_user),db:Session=Depends(get_db)):
    business=scoped(db,user,business_id)
    booking_query=select(Appointment).where(Appointment.business_id==business.id,
        Appointment.reference==reference,Appointment.customer_email==user["email"])
    # Do not hold a PostgreSQL row lock while waiting on a remote routing API.
    row=db.scalar(booking_query)
    if row is None: raise HTTPException(404,"Booking not found")
    now=datetime.now(timezone.utc)
    if row.status not in ("confirmed","at_risk") or utc(row.ends_at)<=now or utc(row.starts_at)>now+timedelta(days=2):
        raise HTTPException(409,"Location is only available shortly before an active visit")
    if not body.captured_at.tzinfo or abs((now-body.captured_at.astimezone(timezone.utc)).total_seconds())>300:
        raise HTTPException(422,"Location timestamp is stale or missing timezone")
    if body.accuracy_meters>250:
        raise HTTPException(422,"Location accuracy is too low. Try again outside or enter your ETA manually")
    if business.latitude is None or business.longitude is None:
        raise HTTPException(409,"Business location is not configured. Ask your admin to set it in Settings")
    try:
        route=estimate_travel(body.latitude,body.longitude,business.latitude,business.longitude,
                              settings.tomtom_routing_api_key)
    except RoutingUnavailable as exc:
        raise HTTPException(503,str(exc)) from exc
    # Revalidate with a row lock before writing arrival status/alerts; the booking
    # might have been cancelled or moved while TomTom calculated the route.
    db.expire_all()
    row=db.scalar(booking_query.with_for_update())
    now=datetime.now(timezone.utc)
    if row is None or row.status not in ("confirmed", "at_risk") or utc(row.ends_at)<=now or utc(row.starts_at)>now+timedelta(days=2):
        raise HTTPException(409, "Appointment changed while checking traffic. Refresh and try again.")
    eta=route["eta_minutes"]
    arrival_at=now+timedelta(minutes=eta)
    grace=timedelta(minutes=business.queue_grace_minutes)
    margin_minutes=round((utc(row.starts_at)-arrival_at).total_seconds()/60)
    predicted="likely_late" if arrival_at>utc(row.starts_at)+grace else ("at_risk" if margin_minutes<5 else "on_time")
    arrival=db.scalar(select(CustomerArrival).where(CustomerArrival.appointment_id==row.id))
    if not arrival:
        arrival=CustomerArrival(appointment_id=row.id)
        db.add(arrival)
    already_late=(arrival.status=="likely_late")
    arrival.status=predicted
    arrival.eta_minutes=min(180,eta)
    arrival.updated_at=now
    if predicted=="likely_late" and not already_late:
        db.add(AdminAlert(business_id=business.id,kind="late_arrival",reference=row.reference,
            message=f"Traffic alert: {row.customer_name} ({row.reference}) is predicted late by TomTom traffic routing. Review possible slots."))
        notify(db,business.id,row.customer_email,
            f"Traffic may delay {row.reference}. Your appointment is unchanged; check Queue & offers or contact reception.")
    db.commit()
    return {"reference":row.reference,"eta_minutes":eta,"distance_km":route["distance_km"], "route_points":route.get("route_points", []), "traffic_delay_minutes":route.get("traffic_delay_minutes", 0),
        "arrival_at":arrival_at.isoformat(),"appointment_at":utc(row.starts_at).isoformat(),
        "status":predicted,"source":route["source"],"traffic_aware":route["traffic_aware"],
        "automatic_rescheduling_allowed":False,
        "note":"Travel time and road distance from TomTom with traffic. GPS coordinates are not stored in SmartSlot. No booking is changed automatically."}


@router.get("/admin/alerts")
def admin_alerts(business_id:int,user=Depends(admin_user),db:Session=Depends(get_db)):
    scoped(db,user,business_id,admin=True)
    alerts=db.scalars(select(AdminAlert).where(AdminAlert.business_id==business_id)
        .order_by(AdminAlert.created_at.desc(),AdminAlert.id.desc()).limit(80)).all()
    return [{"id":a.id,"message":a.message,"kind":a.kind,"reference":a.reference,
             "read":a.read,"created_at":utc(a.created_at).isoformat()} for a in alerts]


@router.post("/admin/alerts/{alert_id}/read")
def mark_alert_read(alert_id:int,business_id:int,user=Depends(admin_user),db:Session=Depends(get_db)):
    scoped(db,user,business_id,admin=True)
    alert=db.scalar(select(AdminAlert).where(AdminAlert.id==alert_id,AdminAlert.business_id==business_id))
    if not alert: raise HTTPException(404,"Alert not found")
    alert.read=True
    db.commit()
    return {"id":alert.id,"read":True}
