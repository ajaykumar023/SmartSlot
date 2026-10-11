"""Create password-based CUSTOMER accounts only for previously seeded fictional AETHERX bookings.

Preview (no DB writes): python seed_demo_logins.py
Apply (after DB backup):
  $env:AETHERX_DEMO_WRITE='YES'
  python seed_demo_logins.py --apply
  Remove-Item Env:AETHERX_DEMO_WRITE

Requires migration 0009_auth_conflicts_delivery. No admin/employee accounts
are created, no existing passwords are reset, and no actual customer data is touched.
"""
from __future__ import annotations
import argparse
import os
from collections import defaultdict
from getpass import getpass
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.account_security import make_hash
from app.database import SessionLocal
from app.models import AccountBusinessRole, Appointment, Business, UserAccount

FICTIONAL_DOMAIN = '@aetherx.example'  # Reserved example domain; no deliverable email addresses.


def eligible_customers(db: Session) -> dict[str, tuple[str, set[int]]]:
    """Identity + branches come from existing appointments, not a hardcoded name list."""
    rows = db.execute(
        select(Appointment.customer_email, Appointment.customer_name, Appointment.business_id)
        .join(Business, Appointment.business_id == Business.id)
        .where(Business.is_demo.is_(True), Business.active.is_(True),
               Business.demo_key.like('showcase_%'))
        .order_by(Appointment.id)
    ).all()
    found: dict[str, tuple[str, set[int]]] = {}
    for email, name, bid in rows:
        email = (email or '').strip().lower()
        if not email.endswith(FICTIONAL_DOMAIN) or not name or len(name.strip()) < 2:
            continue
        if email not in found:
            found[email] = (name.strip(), set())
        found[email][1].add(bid)
    return found


def seed_logins(db: Session, password: str) -> dict[str, int]:
    """Only create absent identities. Never overwrite a password or grant on an existing identity."""
    people = eligible_customers(db)
    # Check valid password up front, even when all accounts already exist.
    if not 12 <= len(password) <= 256:
        raise ValueError('Demo account password must be between 12 and 256 characters')
    results = {'eligible': len(people), 'accounts_created': 0, 'grants_created': 0,
               'existing_accounts_skipped': 0}
    for email, (name, branches) in sorted(people.items()):
        existing = db.scalar(select(UserAccount).where(UserAccount.email == email))
        if existing is not None:
            results['existing_accounts_skipped'] += 1
            continue  # Existing identities may be real logins; never modify their access.
        salt, digest = make_hash(password)
        account = UserAccount(email=email, name=name, password_salt=salt,
                              password_hash=digest, active=True, auth_version=1)
        db.add(account)
        db.flush()
        for business_id in sorted(branches):
            db.add(AccountBusinessRole(account_id=account.id, business_id=business_id,
                                       role='customer', staff_id=None))
            results['grants_created'] += 1
        results['accounts_created'] += 1
    db.flush()
    return results


def main():
    parser = argparse.ArgumentParser(description='Seed password login for fictional showcase CUSTOMERS')
    parser.add_argument('--apply', action='store_true', help='Insert accounts into the configured database')
    args = parser.parse_args()
    with SessionLocal() as db:
        people = eligible_customers(db)
        print(f'Fictional customer identities found in database: {len(people)}')
        for email, (name, branches) in list(sorted(people.items()))[:10]:
            print(f'  {name:24} {email:42} allowed business IDs: {sorted(branches)}')
        print('All account names/emails are taken from existing fictional booking records.')
        if not args.apply:
            print('PREVIEW ONLY: PostgreSQL is unchanged. Use --apply after creating a backup.')
            return
        if os.getenv('AETHERX_DEMO_WRITE') != 'YES':
            parser.error('Refusing write; set AETHERX_DEMO_WRITE=YES for this command only')
        if not people:
            parser.error('No eligible fictional showcase bookings found; seed demo bookings first')
        pw = getpass('Password for NEW fictional customer accounts (12+ chars; hidden): ')
        confirm = getpass('Repeat password: ')
        if pw != confirm:
            parser.error('Passwords differ; nothing was saved')
        if len(pw) < 12:
            parser.error('Minimum password length is 12; try Welcome1234! for LOCAL FICTIONAL demo ONLY')
        summary = seed_logins(db, pw)
        db.commit()
        print('Account creation committed:', summary)
        print('Passwords were salted and hashed; existing accounts were not modified.')
        print('DO NOT use these shared demo credentials or fictional identities on a public deployment.')


if __name__ == '__main__':
    main()
