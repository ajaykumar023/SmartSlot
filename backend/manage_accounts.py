"""Provision real SmartSlot accounts, with no passwords in command history.
Run from backend/ after Alembic migrations are applied.
"""
import argparse
from getpass import getpass
from sqlalchemy import select
from app.account_security import make_hash
from app.database import SessionLocal
from app.models import AccountBusinessRole, Business, Staff, UserAccount


def main():
    parser = argparse.ArgumentParser(description='Provision authenticated SmartSlot users (password prompt hidden)')
    parser.add_argument('action', choices=['create', 'grant', 'reset-password', 'disable'])
    parser.add_argument('--email', required=True)
    parser.add_argument('--name', default='')
    parser.add_argument('--business-id', type=int)
    parser.add_argument('--role', choices=['admin', 'employee', 'customer'])
    parser.add_argument('--staff-id', type=int)
    args = parser.parse_args()
    email = args.email.lower().strip()
    if '@' not in email or not email.split('@')[-1].count('.'):
        parser.error('Use a valid email address')
    if args.action in ('create', 'grant') and (not args.business_id or not args.role):
        parser.error('Specify --business-id and --role')
    if args.action == 'create' and len(args.name.strip()) < 2:
        parser.error('Specify --name for a new account')

    password = None
    if args.action in ('create', 'reset-password'):
        password = getpass('New password (minimum 12 characters): ')
        if password != getpass('Repeat password: '):
            parser.error('Passwords did not match')
        salt, digest = make_hash(password)

    with SessionLocal.begin() as db:
        acc = db.scalar(select(UserAccount).where(UserAccount.email == email))
        if args.action == 'create':
            if acc:
                parser.error('Account exists; use grant or reset-password')
            acc = UserAccount(email=email, name=args.name.strip(), password_salt=salt,
                              password_hash=digest, active=True, auth_version=1)
            db.add(acc)
            db.flush()
        elif not acc:
            parser.error('Account not found')
        if args.action in ('create', 'grant'):
            business = db.get(Business, args.business_id)
            if not business:
                parser.error('Business does not exist. List IDs from PostgreSQL first')
            if args.role == 'employee':
                person = db.get(Staff, args.staff_id) if args.staff_id else None
                if not person or person.business_id != args.business_id:
                    parser.error('Employee must have --staff-id belonging to this business')
            elif args.staff_id is not None:
                parser.error('--staff-id is valid only for the employee role')
            grant = db.scalar(select(AccountBusinessRole).where(
                AccountBusinessRole.account_id == acc.id,
                AccountBusinessRole.business_id == args.business_id,
                AccountBusinessRole.role == args.role))
            if grant:
                parser.error('This account already has that permission')
            db.add(AccountBusinessRole(account_id=acc.id, business_id=args.business_id,
                                       role=args.role, staff_id=args.staff_id))
        elif args.action == 'reset-password':
            acc.password_salt, acc.password_hash = salt, digest
            acc.auth_version += 1  # Invalidates every outstanding token.
        elif args.action == 'disable':
            acc.active = False
            acc.auth_version += 1
    print('Account change saved. No password was written to a log or manifest.')


if __name__ == '__main__':
    main()
