"""Password accounts and least-privilege employee access."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .account_security import verify_hash
from .auth import current_user, issue_token
from .config import settings
from .database import get_db
from .models import AccountBusinessRole, Appointment, Availability, Business, Staff, StaffPresence, UserAccount, Service, Notification, NotificationDelivery

router = APIRouter(prefix='/api', tags=['Account security and staff'])


class PasswordLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    business_id: int = Field(gt=0)
    role: str = Field(pattern='^(admin|employee|customer)$')


@router.post('/auth/login')
def password_login(body: PasswordLogin, db: Session = Depends(get_db)):
    if len(settings.app_secret) < 32 or settings.app_secret == 'local-demo-secret-change-me':
        raise HTTPException(503, 'Configure a unique APP_SECRET of at least 32 characters before using secure login')
    email = body.email.lower().strip()
    acc = db.scalar(select(UserAccount).where(UserAccount.email == email))
    # Maintain similar password-check cost even when account doesn't exist.
    if not acc:
        from .account_security import make_hash
        verify_hash(body.password, '0' * 48, '0' * 64)
        raise HTTPException(401, 'Invalid credentials or business permission')
    if not acc.active or not verify_hash(body.password, acc.password_salt, acc.password_hash):
        raise HTTPException(401, 'Invalid credentials or business permission')
    grant = db.scalar(select(AccountBusinessRole).where(AccountBusinessRole.account_id == acc.id,
        AccountBusinessRole.business_id == body.business_id, AccountBusinessRole.role == body.role))
    business = db.get(Business, body.business_id)
    if not grant or not business or not business.active:
        raise HTTPException(403, 'No permission for this business and role')
    if body.role == 'employee' and (grant.staff_id is None or not db.get(Staff, grant.staff_id)):
        raise HTTPException(403, 'Employee has no valid staff assignment')
    grants = db.scalars(select(AccountBusinessRole).where(AccountBusinessRole.account_id == acc.id,
                                                     AccountBusinessRole.role == body.role)).all()
    token = issue_token(body.role, acc.name, acc.email, body.business_id,
                        [g.business_id for g in grants], account_id=acc.id, auth_version=acc.auth_version)
    return {'access_token': token, 'token_type': 'bearer',
            'user': {'role': body.role, 'name': acc.name, 'email': acc.email, 'business_id': body.business_id}}


@router.get('/auth/me')
def who_am_i(user=Depends(current_user)):
    return {k: user.get(k) for k in ('role', 'name', 'email', 'business_id', 'business_ids', 'staff_id')}


def require_employee(user: dict, business_id: int):
    if user.get('role') != 'employee' or user.get('business_id') != business_id or not user.get('staff_id'):
        raise HTTPException(403, 'Employee access to own branch required')


@router.get('/employee/my-appointments')
def my_work(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_employee(user, business_id)
    rows = db.scalars(select(Appointment).where(Appointment.business_id == business_id,
        Appointment.staff_id == user['staff_id'], Appointment.status.in_(['confirmed', 'at_risk', 'checked_in']))
        .order_by(Appointment.starts_at).limit(50)).all()
    return [{'reference': b.reference, 'name': b.customer_name, 'service_id': b.service_id,
             'starts_at': b.starts_at, 'ends_at': b.ends_at, 'status': b.status} for b in rows]


class EmployeePresence(BaseModel):
    status: str = Field(pattern='^(on_site|break|away)$')


@router.put('/employee/my-presence')
def update_my_presence(business_id: int, body: EmployeePresence,
                       user=Depends(current_user), db: Session = Depends(get_db)):
    require_employee(user, business_id)
    row = db.scalar(select(StaffPresence).where(StaffPresence.business_id == business_id,
                                                         StaffPresence.staff_id == user['staff_id']))
    if row is None:
        row = StaffPresence(business_id=business_id, staff_id=user['staff_id'])
        db.add(row)
    row.status = body.status
    row.source = 'employee_authenticated'
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {'staff_id': user['staff_id'], 'business_id': business_id, 'status': row.status}


@router.get('/admin/notification-delivery-status')
def delivery_overview(business_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    if user.get('role') != 'admin' or business_id not in user.get('business_ids', []):
        raise HTTPException(403, 'Admin access required for selected branch')
    rows = db.execute(select(NotificationDelivery.status, Notification.id).join(Notification,
        Notification.id == NotificationDelivery.notification_id).where(Notification.business_id == business_id)).all()
    totals = {state: sum(1 for st, _ in rows if st == state) for state in ('pending', 'retry', 'accepted_by_webhook')}
    total = len(db.scalars(select(Notification.id).where(Notification.business_id == business_id)).all())
    return {'notifications_created': total, 'webhook_delivery': totals,
            'not_processed': total - len(rows), 'webhook_configured': bool(settings.notification_webhook_url),
            'note': 'Webhook HTTP acceptance is not proof of email/SMS delivery to recipient'}
