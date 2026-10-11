"""Read-only verification BEFORE applying 0009; never modifies bookings."""
from sqlalchemy import text
from app.database import engine

sql = '''
 SELECT a.id AS appointment_a, b.id AS appointment_b, a.staff_id,
        a.reference AS reference_a, b.reference AS reference_b
 FROM appointments a JOIN appointments b ON a.staff_id=b.staff_id AND a.id<b.id
 WHERE a.status IN ('confirmed','checked_in','at_risk')
   AND b.status IN ('confirmed','checked_in','at_risk')
   AND tstzrange(a.starts_at,a.ends_at+a.buffer_minutes*interval '1 minute','[)')
       && tstzrange(b.starts_at,b.ends_at+b.buffer_minutes*interval '1 minute','[)')
 ORDER BY a.staff_id,a.id LIMIT 20
'''
with engine.connect() as c:
    if c.dialect.name!='postgresql':
        raise SystemExit('This preflight requires your PostgreSQL Docker database')
    conflicts=c.execute(text(sql)).mappings().all()
    print('Conflicting active appointment pairs (first 20):',len(conflicts))
    for row in conflicts:
        print('Staff:',row['staff_id'],'appointment IDs:',row['appointment_a'],row['appointment_b'],
              'references:',row['reference_a'],row['reference_b'])
    if conflicts:
        raise SystemExit('STOP: fix these appointments first; do NOT stamp or delete migrations')
    print('PASS: No existing active staff-overlap detected. PostgreSQL 0009 may now be attempted.')
