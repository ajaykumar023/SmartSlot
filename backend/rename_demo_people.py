"""Preview or safely rename old fictional SmartSlot showcase labels IN PLACE.

Only AETHERX demo businesses, seeded reference patterns and .example emails are
eligible. Primary keys, emails, role grants, bookings and dates do not change.
Run from backend/: python rename_demo_people.py [--apply]
"""
from __future__ import annotations

import argparse
import os
import re
from collections import Counter
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models import Appointment, Business, Staff, WaitlistEntry, UserAccount
from demo_identity_names import (
    STAFF_DISPLAY_NAMES, fictional_customer_name,
    SCENARIO_CUSTOMERS, WAITLIST_CUSTOMERS,
)

_DEMO_BOOKING = re.compile(r"^SS-WF-(\d{4})$")
_SHOWCASE_PREFIX = "showcase_"
_DOMAIN = "@aetherx.example"
_OLD_GENERIC = re.compile(r"^(?:Demo Customer \d{3}|Alex Morgan|Demo (?:Local|Branch|Clinic|Repair|Consulting|Cancelled) .*)$")


def name_for_booking(row: Appointment) -> str | None:
    if not row.customer_email.lower().endswith(_DOMAIN):
        return None
    match = _DEMO_BOOKING.fullmatch(row.reference)
    if match and row.customer_email.lower() == f"showcase.customer{(int(match.group(1))-1)%100+1:03d}{_DOMAIN}":
        return fictional_customer_name((int(match.group(1)) - 1) % 100 + 1)
    if row.reference.startswith("SS-DM-"):
        return SCENARIO_CUSTOMERS.get(row.customer_email.lower())
    return None


def propose_renames(db) -> tuple[list, Counter]:
    """Return (target, value) operations without updating the session."""
    businesses = db.scalars(select(Business).where(Business.is_demo.is_(True))).all()
    demo = {b.id: b for b in businesses if b.demo_key and b.demo_key.startswith(_SHOWCASE_PREFIX)}
    operations = []
    counter = Counter()
    for bid, business in demo.items():
        staff = db.scalars(select(Staff).where(Staff.business_id == bid)).all()
        used_names = {p.name: p.id for p in staff}
        for person in staff:
            new = STAFF_DISPLAY_NAMES.get(business.demo_key, {}).get(person.name)
            if new and new != person.name:
                if new in used_names and used_names[new] != person.id:
                    raise ValueError(f"Duplicate staff display name {new!r}; no changes made")
                operations.append((person, new)); counter["staff"] += 1
        bookings = db.scalars(select(Appointment).where(Appointment.business_id == bid)).all()
        for row in bookings:
            new = name_for_booking(row)
            if new and row.customer_name != new and (_OLD_GENERIC.fullmatch(row.customer_name) or
                    _DEMO_BOOKING.fullmatch(row.reference)):
                operations.append((row, new)); counter["bookings"] += 1
        waitlist = db.scalars(select(WaitlistEntry).where(WaitlistEntry.business_id == bid)).all()
        for row in waitlist:
            new = WAITLIST_CUSTOMERS.get(row.customer_email.lower())
            if new and row.customer_name.startswith("Demo ") and row.customer_name != new:
                operations.append((row, new)); counter["waitlist"] += 1
    # Only update known synthetic accounts, never staff/user accounts under genuine domains.
    synthetic_emails = {f"showcase.customer{n:03d}{_DOMAIN}" for n in range(1, 101)}
    synthetic_emails.update(SCENARIO_CUSTOMERS)
    for account in db.scalars(select(UserAccount).where(UserAccount.email.in_(synthetic_emails))).all():
        email = account.email.lower()
        new = SCENARIO_CUSTOMERS.get(email)
        if not new and email.startswith('showcase.customer'):
            number = int(email[len('showcase.customer'):len('showcase.customer')+3])
            new = fictional_customer_name(number)
        if new and account.name != new and _OLD_GENERIC.fullmatch(account.name):
            operations.append((account, new)); counter["accounts"] += 1
    return operations, counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit name changes on the demo PostgreSQL database')
    args = parser.parse_args()
    if args.apply:
        if os.environ.get('AETHERX_DEMO_WRITE') != 'YES':
            parser.error('Set AETHERX_DEMO_WRITE=YES explicitly to permit demo renaming')
        if engine.dialect.name != 'postgresql':
            parser.error('Only apply on the development PostgreSQL database')
    with SessionLocal() as db:
        changes, counts = propose_renames(db)
        print('Demo names to update:', dict(counts), 'total', len(changes))
        for obj, new in changes[:12]:
            old = obj.customer_name if isinstance(obj, (Appointment, WaitlistEntry)) else obj.name
            print(f'  {type(obj).__name__} #{obj.id}: {old!r} -> {new!r}')
        if len(changes) > 12:
            print('  ...')
        if not args.apply:
            print('PREVIEW ONLY: no changes saved. Use --apply with explicit opt-in.')
            return
        for obj, new in changes:
            if isinstance(obj, (Appointment, WaitlistEntry)):
                obj.customer_name = new
            else:
                obj.name = new
        db.commit()
        print('COMMITTED. Booking IDs, emails, times, QR passes and staff assignments unchanged.')


if __name__ == '__main__':
    main()
