"""Read-only PostgreSQL preflight; optional live TomTom request (billable)."""
import argparse
from sqlalchemy import text
from app.database import engine
from app.config import settings

p=argparse.ArgumentParser()
p.add_argument('--tomtom', action='store_true', help='Send one real TomTom route request')
args=p.parse_args()
with engine.connect() as c:
    if c.dialect.name != 'postgresql':
        raise SystemExit('ERROR: This verifier must run against PostgreSQL, not SQLite')
    version = c.execute(text('SELECT version_num FROM alembic_version')).scalar()
    constraint = c.execute(text("SELECT COUNT(*) FROM pg_constraint WHERE conname='ex_aetherx_active_staff_occupied'")).scalar()
    conflict = c.execute(text('''
     SELECT a.id,b.id FROM appointments a JOIN appointments b ON a.staff_id=b.staff_id AND a.id<b.id
     WHERE a.status IN ('confirmed','checked_in','at_risk') AND b.status IN ('confirmed','checked_in','at_risk')
     AND tstzrange(a.starts_at, a.ends_at+a.buffer_minutes*interval '1 minute', '[)') &&
         tstzrange(b.starts_at, b.ends_at+b.buffer_minutes*interval '1 minute', '[)') LIMIT 1
    ''')).first()
    print('Alembic revision:', version)
    print('PostgreSQL exclusion constraint:', 'PRESENT' if constraint else 'MISSING')
    print('Existing overlapping active bookings:', conflict or 'none')
    print('Password accounts:', c.execute(text('SELECT count(*) FROM user_accounts')).scalar())
    print('Notification delivery rows:', c.execute(text('SELECT count(*) FROM notification_deliveries')).scalar())
    print('Recovery events:', c.execute(text('SELECT count(*) FROM recovery_events')).scalar())
    if not constraint or conflict:
        raise SystemExit('FAIL: Resolve database issues before demo')
if args.tomtom:
    from app.georoutes import estimate_travel, RoutingUnavailable
    print('TomTom configured:', bool(settings.tomtom_routing_api_key))
    if not settings.tomtom_routing_api_key:
        raise SystemExit('FAIL: No TomTom server key')
    try:
        route=estimate_travel(12.9716,77.5946,12.9352,77.6245,settings.tomtom_routing_api_key)
        print('REAL TomTom source:',route['source'],'ETA min:',route['eta_minutes'])
    except RoutingUnavailable as err:
        raise SystemExit('Live TomTom request failed') from err
