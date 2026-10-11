"""At-least-once delivery to a configured trusted webhook.

This does not send email/SMS itself. The receiver must use Idempotency-Key to
avoid duplicate sends after network failures.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from .config import settings
from .models import Notification, NotificationDelivery


def validated_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and bool(parsed.netloc) and not parsed.username and not parsed.password) or (
        parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port is not None)


def deliver_pending(db: Session, *, max_count: int = 20, sender=None) -> dict:
    """Uses row locks on PostgreSQL to serialize concurrent dispatch workers."""
    url = settings.notification_webhook_url.strip()
    secret = settings.notification_webhook_secret.strip()
    if not validated_endpoint(url) or len(secret) < 24:
        raise ValueError('Set HTTPS NOTIFICATION_WEBHOOK_URL and NOTIFICATION_WEBHOOK_SECRET (24+ chars)')
    sender = sender or _post
    now = datetime.now(timezone.utc)
    pending = select(Notification).outerjoin(NotificationDelivery,
        NotificationDelivery.notification_id == Notification.id).where(
        or_(NotificationDelivery.id.is_(None),
            (NotificationDelivery.status == 'retry') &
            (NotificationDelivery.next_attempt_at <= now))).order_by(Notification.id).limit(min(max_count, 100))
    if db.bind.dialect.name == 'postgresql':
        pending = pending.with_for_update(of=Notification, skip_locked=True)
    count = accepted = failed = 0
    for note in db.scalars(pending).all():
        ledger = db.scalar(select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id))
        if ledger is None:
            ledger = NotificationDelivery(notification_id=note.id, status='pending', attempts=0)
            db.add(ledger)
            db.flush()
        if ledger.status == 'accepted_by_webhook':
            continue
        payload = json.dumps({'id': note.id, 'business_id': note.business_id,
            'recipient_email': note.customer_email, 'message': note.message,
            'created_at': note.created_at.isoformat() if note.created_at else None},
            separators=(',', ':')).encode()
        signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        count += 1
        try:
            sender(url, payload, f'sha256={signature}', f'notification-{note.id}')
            ledger.status = 'accepted_by_webhook'
            ledger.delivered_at = datetime.now(timezone.utc)
            ledger.last_error = None
            accepted += 1
        except Exception as exc:
            ledger.status = 'retry'
            ledger.last_error = type(exc).__name__[:200]  # Do not save credentials, URLs or PII from errors.
            ledger.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * 2 ** min(ledger.attempts, 7)))
            failed += 1
        ledger.attempts += 1
        db.flush()
    return {'processed': count, 'accepted_by_webhook': accepted, 'failed_retry_scheduled': failed,
            'note': 'A webhook HTTP 2xx response is NOT proof of email/SMS delivery.'}


def _post(url: str, payload: bytes, signature: str, event_id: str):
    request = Request(url, data=payload, method='POST', headers={
        'Content-Type': 'application/json',
        'X-Aetherx-Signature': signature,
        'Idempotency-Key': event_id,
        'User-Agent': 'AETHERX-SmartSlot/1.0'})
    with urlopen(request, timeout=8) as response:
        if not (200 <= response.status < 300):
            raise RuntimeError('Provider did not accept webhook')
