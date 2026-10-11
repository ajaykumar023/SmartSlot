"""Signed sessions backed by an active provisioned account and branch membership.

Insecure demo identities are explicitly opt-in for LOCAL fictional demos only.
"""
import base64
import hashlib
import hmac
import json
import time
from fastapi import HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from .models import UserAccount, AccountBusinessRole

bearer = HTTPBearer(auto_error=False)


def issue_token(role: str, name: str, email: str, business_id: int,
                business_ids: list[int] | None = None, *,
                account_id: int | None = None, auth_version: int | None = None) -> str:
    payload = {"role": role, "name": name, "email": email.lower(), "business_id": business_id,
               "business_ids": business_ids or [business_id], "exp": int(time.time()) + (43200 if account_id else 86400)}
    if account_id is not None:
        payload['account_id'] = account_id
        payload['auth_version'] = auth_version
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    sig = hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f'{body}.{sig}'


def _decode(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if not credentials:
        raise HTTPException(401, 'Sign in to continue')
    try:
        if credentials.scheme.lower() != 'bearer':
            raise ValueError('scheme')
        body, signature = credentials.credentials.split('.', 1)
        expected = hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('signature')
        raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
        user = json.loads(raw)
        if not isinstance(user, dict) or user['exp'] <= time.time():
            raise ValueError('expired')
        return user
    except Exception as exc:
        raise HTTPException(401, 'Session expired. Please sign in again.') from exc


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)):
    user = _decode(credentials)
    # Demo tokens remain valid only behind explicit insecure-demo switches.
    if 'account_id' not in user:
        if not settings.allow_insecure_demo_login or (user.get('role') == 'admin' and not settings.allow_insecure_demo_admin):
            raise HTTPException(401, 'Demo login disabled; use password-based login')
        return user
    if not isinstance(db, Session):
        raise HTTPException(401, 'Cannot validate account against database')
    account = db.get(UserAccount, user['account_id'])
    if not account or not account.active or account.auth_version != user.get('auth_version') or account.email != user.get('email'):
        raise HTTPException(401, 'Account disabled or session revoked; sign in again')
    role = user.get('role')
    selected_business = user.get('business_id')
    memberships = db.scalars(select(AccountBusinessRole).where(AccountBusinessRole.account_id == account.id,
                                                    AccountBusinessRole.role == role)).all()
    selected = next((g for g in memberships if g.business_id == selected_business), None)
    if not selected:
        raise HTTPException(403, 'Your business permission has been revoked')
    # Rebuild permitted branches from database; never trust claims in session alone.
    user['business_ids'] = [g.business_id for g in memberships]
    user['name'] = account.name
    user['staff_id'] = selected.staff_id
    return user


def admin_user(user=Depends(current_user)):
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Admin access required')
    return user
