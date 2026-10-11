"""Optional LIVE FastAPI smoke test. Dry-run won't reassign bookings.

May write an admin alert for an unresolved recovery attempt. Only use a fictional
booking with a known staff disruption and an account token you own.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

p=argparse.ArgumentParser(description='One live dry-run Smart Recovery API request')
p.add_argument('--reference', required=True)
p.add_argument('--business-id', required=True, type=int)
p.add_argument('--lat', type=float)
p.add_argument('--lon', type=float)
p.add_argument('--accuracy', type=float, default=50)
a=p.parse_args()
token=os.environ.get('AETHERX_TEST_BEARER_TOKEN','').strip()
if not token:
    raise SystemExit('Set AETHERX_TEST_BEARER_TOKEN to the fictional customer access token first')
if (a.lat is None)!=(a.lon is None):
    raise SystemExit('Supply --lat and --lon together, or neither for same-branch test')
body={'dry_run':True}
if a.lat is not None:
    body.update(latitude=a.lat, longitude=a.lon, accuracy_meters=a.accuracy,
                captured_at=datetime.now(timezone.utc).isoformat())
base=os.environ.get('AETHERX_API_URL','http://127.0.0.1:8000').rstrip('/')
url=f'{base}/api/appointments/{a.reference}/recover?business_id={a.business_id}'
request=Request(url,data=json.dumps(body).encode(),method='POST',headers={
    'Content-Type':'application/json','Authorization':'Bearer '+token})
try:
    with urlopen(request,timeout=25) as resp:
        result=json.load(resp)
        print('HTTP:',resp.status, 'Recovery dry run status:',result.get('status'))
        print('Reason:',result.get('reason',''))
        print('Appointment unchanged:',result.get('appointment_unchanged'))
        print('Proposed candidate:', result.get('candidate'))
        if result.get('status')!='candidate':
            print('No feasible candidate proven. Check staff disruption, policy, qualifications and route.')
except HTTPError as e:
    print('HTTP:',e.code, 'Error:',e.read().decode('utf-8','replace')[:300])
    raise SystemExit(1)
except URLError as e:
    raise SystemExit('FastAPI is unavailable or network blocked') from e
