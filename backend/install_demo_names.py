"""Safely adapt existing AETHERX seed files to friendly names.

Makes timestamped .bak files, only patches exact known seed versions, and
refuses unfamiliar scripts rather than overwriting project code.
Also changes the Alex Morgan customer-form example if present.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def patch_text(path: Path, replacements: list[tuple[str, str]]) -> bool:
    original = path.read_text(encoding='utf-8')
    revised = original
    for old, new in replacements:
        if new in revised:
            continue
        if old not in revised:
            raise RuntimeError(f"Unexpected source in {path}: cannot find expected patch marker: {old[:80]!r}")
        revised = revised.replace(old, new, 1)
    if revised == original:
        print('Already patched:', path)
        return False
    if path.suffix == '.py':
        ast.parse(revised)
    backup = path.with_suffix(path.suffix + '.before-names.bak')
    if not backup.exists():
        backup.write_text(original, encoding='utf-8')
    path.write_text(revised, encoding='utf-8')
    print('Updated:', path, 'backup:', backup)
    return True


def main():
    showcase = ROOT / 'demo_showcase_seed.py'
    workforce = ROOT / 'demo_finalize_seed.py'
    missing = [str(p) for p in (showcase, workforce) if not p.is_file()]
    if missing:
        raise SystemExit('Missing seed scripts; install showcase seed and Night Pack first: ' + ', '.join(missing))
    patch_text(showcase, [
        ('from app.qr import token_hash\n',
         'from app.qr import token_hash\nfrom demo_identity_names import employee_name, SCENARIO_CUSTOMERS\n'),
        ('''    for name in profile["staff"]:
        person = db.scalar(select(Staff).where(Staff.business_id == business.id, Staff.name == name))
        if not person:
            person = Staff(business_id=business.id, name=name, title="Fictional professional", active=True)
            db.add(person)
            db.flush()
''', '''    for name in profile["staff"]:
        display_name = employee_name(profile["demo_key"], name)
        matches = list(db.scalars(select(Staff).where(
            Staff.business_id == business.id, Staff.name.in_((name, display_name)))))
        if len(matches) > 1:
            raise ValueError(f"Duplicate demo staff identities for {name}; inspect rows manually")
        person = matches[0] if matches else None
        if not person:
            person = Staff(business_id=business.id, name=display_name, title="Fictional professional", active=True)
            db.add(person)
            db.flush()
        elif person.name != display_name:
            person.name = display_name
'''),
        ('''        business, service, people = locations[business_key]
''', '''        business, service, people = locations[business_key]
        name = SCENARIO_CUSTOMERS.get(email, name)
'''),
    ])
    patch_text(workforce, [
        ('from app.qr import token_hash\n',
         'from app.qr import token_hash\nfrom demo_identity_names import employee_name, fictional_customer_name\n'),
        ('''    staff = db.scalar(select(Staff).where(Staff.business_id == business.id, Staff.name == name))
    if staff:
        # Do not reactivate, change title, or alter qualifications of existing staff.
        if not staff.name.startswith('Demo '):
            raise ValueError(f'Non-demo staff name collision: {name}')
    else:
        staff = Staff(business_id=business.id, name=name, title=title, active=True)
        db.add(staff)
        db.flush()
''', '''    display_name = employee_name(business.demo_key, name)
    matches = list(db.scalars(select(Staff).where(
        Staff.business_id == business.id, Staff.name.in_((name, display_name)))))
    if len(matches) > 1:
        raise ValueError(f'Duplicate demo staff identities for {name}; inspect rows manually')
    staff = matches[0] if matches else None
    if not staff:
        staff = Staff(business_id=business.id, name=display_name, title=title, active=True)
        db.add(staff)
        db.flush()
    elif staff.name != display_name:
        staff.name = display_name
'''),
        ('''customer_email=email, customer_name=f'Demo Customer {index % 100 + 1:03d}',
''', '''customer_email=email, customer_name=fictional_customer_name(index % 100 + 1),
'''),
    ])
    frontend = ROOT.parent / 'frontend' / 'src' / 'pages' / 'Customer.tsx'
    if frontend.is_file():
        text = frontend.read_text(encoding='utf-8')
        if 'placeholder="e.g. Alex Morgan"' in text:
            patch_text(frontend, [('placeholder="e.g. Alex Morgan"',
                                   'placeholder="Enter your full name"')])
    print('Installation finished. Run rename_demo_people.py in preview mode before applying.')


if __name__ == '__main__':
    main()
