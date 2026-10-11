"""Admin-only operational read APIs; uses existing PostgreSQL tables.

No customer medical details or booking notes returned. Demo authentication is
not suitable for real customer records; use with fictional data only.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import admin_user
from .database import get_db
from .models import (
    AdminAlert, Appointment, Business, Staff, StaffAbsence, StaffPresence,
    StaffService, WaitlistEntry,
)
from .queue_engine import utc

router = APIRouter(prefix='/api/admin/ops', tags=['Admin Operations'])


def _check_business(db: Session, business_id: int, user: dict) -> Business:
    business = db.get(Business, business_id)
    if not business or not business.active:
        raise HTTPException(404, 'Business not found')
    if business_id not in user.get('business_ids', []):
        raise HTTPException(403, 'You do not have access to this branch')
    return business


def _bounds(business: Business, on_date: date | None) -> tuple[datetime, datetime, date]:
    tz = ZoneInfo(business.timezone)
    day = on_date or datetime.now(tz).date()
    first = datetime.combine(day, time.min, tz).astimezone(timezone.utc)
    last = datetime.combine(day + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
    return first, last, day


def _headcount(db: Session, business_id: int) -> tuple[list[Staff], set[int]]:
    staff = list(db.scalars(select(Staff).where(Staff.business_id == business_id).order_by(Staff.id)))
    staff_ids = [s.id for s in staff]
    if not staff_ids:
        return staff, set()
    qualified = set(db.scalars(select(StaffService.staff_id)
        .where(StaffService.staff_id.in_(staff_ids))).all())
    return staff, qualified


@router.get('/summary')
def summary(business_id: int = Query(ge=1), on_date: date | None = None,
            user: dict = Depends(admin_user), db: Session = Depends(get_db)):
    business = _check_business(db, business_id, user)
    start, end, selected = _bounds(business, on_date)
    staff, bookable = _headcount(db, business.id)
    bookings = list(db.scalars(select(Appointment).where(
        Appointment.business_id == business.id,
        Appointment.starts_at >= start, Appointment.starts_at < end)).all())
    statuses = Counter(row.status for row in bookings)
    waitlist = list(db.scalars(select(WaitlistEntry).where(
        WaitlistEntry.business_id == business.id,
        WaitlistEntry.status == 'waiting')).all())
    unread = list(db.scalars(select(AdminAlert.id).where(
        AdminAlert.business_id == business.id, AdminAlert.read.is_(False))).all())
    absences = list(db.scalars(select(StaffAbsence).where(
        StaffAbsence.business_id == business.id,
        StaffAbsence.starts_at < end, StaffAbsence.ends_at > start)).all())
    return {
        'business_id': business.id, 'business_name': business.name,
        'timezone': business.timezone, 'date': selected.isoformat(),
        'staff': {'total': len(staff), 'active': sum(s.active for s in staff),
                  'bookable_professionals': len(bookable),
                  'support_staff': len(staff) - len(bookable)},
        'appointments': {'total': len(bookings), 'by_status': dict(sorted(statuses.items()))},
        'waiting_customers': len(waitlist), 'unread_admin_alerts': len(unread),
        'staff_absence_intervals': len(absences),
        'note': 'Counts only; demo sessions are not production authentication.',
    }


@router.get('/team')
def team(business_id: int = Query(ge=1), on_date: date | None = None,
         user: dict = Depends(admin_user), db: Session = Depends(get_db)):
    business = _check_business(db, business_id, user)
    start, end, selected = _bounds(business, on_date)
    staff, bookable = _headcount(db, business.id)
    presence_rows = list(db.scalars(select(StaffPresence).where(
        StaffPresence.business_id == business.id)).all())
    presence = {row.staff_id: row for row in presence_rows}
    absences = list(db.scalars(select(StaffAbsence).where(
        StaffAbsence.business_id == business.id,
        StaffAbsence.starts_at < end, StaffAbsence.ends_at > start)).all())
    absences_count = Counter(row.staff_id for row in absences)
    return {'business_id': business.id, 'date': selected.isoformat(), 'team': [
        {'id': member.id, 'name': member.name, 'title': member.title,
         'active': member.active, 'bookable': member.id in bookable,
         'reported_presence': presence[member.id].status if member.id in presence else 'not_reported',
         'absence_intervals_on_date': absences_count[member.id]}
        for member in staff
    ]}
