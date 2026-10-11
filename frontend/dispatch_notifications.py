"""Explicit run-once webhook dispatcher; run periodically with Task Scheduler or cron."""
import argparse
from app.database import SessionLocal
from app.notification_outbox import deliver_pending

p = argparse.ArgumentParser()
p.add_argument('--apply', action='store_true', help='Actually POST notifications to configured webhook')
p.add_argument('--limit', type=int, default=20)
args = p.parse_args()
if not args.apply:
    print('Dry run only. Use --apply to post pending notifications to your trusted configured webhook.')
else:
    with SessionLocal.begin() as db:
        print(deliver_pending(db, max_count=args.limit))
