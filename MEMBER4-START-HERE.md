# Team Aetherx — Member 4 backend implementation

## Your actual deliverables

This copy is forked from `01-AJAY-CUSTOMER`. **Do not overwrite** Ajay's Customer.tsx or the admin teammate's Admin.tsx. Your owned deliverables are `backend/app` changes, `backend/migrations/versions/0003_member4_queue.py`, `backend/tests/test_member4_flow.py`, `backend/seed_scenarios.py`, and the additive `frontend/src/member4-api.ts` integration wrapper.

### What is actually implemented (not aspirational)

1. QR passes are 32-byte random bearer secrets whose SHA-256 hashes, not secrets, are stored server-side. PNGs are returned during booking/offer acceptance. An authenticated customer can **reissue** a lost pass (invalidating the old pass). Admins can *preview* validation then check in. Reject unknown, wrong-business, cancelled, duplicate, too-early and ended scans. The booking reference is a weaker admin-only manual fallback.
2. Waitlist: enter once per service/day; view/withdraw own requests; exact-service, date and staff-feasible FIFO matching; exclusive 20-minute pending hold; correct recipient authorization; accept/decline/expiry; expired/declined offer re-offered to next eligible customer; accept creates a new booking and fresh QR. Time-of-day is not selected by waitlist entries, and notifications are **simulated in-app**.
3. Smart Queue Shift: explainable 15/30/45/60-minute suggestions, conflict and buffer checking, verified qualification and business/staff opening hours, short-term manual presence guard, admin offers, customer consent, revalidation on acceptance and old slot preserved until acceptance. **No** trained model, real geolocation or automatic double booking.
4. Arrival: customer self-reported ETA/on-the-way (not location verification); admin-entered staff on-site/away/break (not connected to RFID); queue overview and approximate queue positions; no-show risk only after appointment start + grace; manual no-show confirmation.
5. Seed script: generates fictional clinic appointments, waitlist offers, example arrival, private QR cards. Test suite includes multi-tenant, check-in, reissue, waitlist and queue cases.

## 1. Setup on Windows (PowerShell)

Requirements: Python **3.11 or 3.12** recommended, Node.js 20+, Docker Desktop running, PowerShell. Use this package folder, not the original `01-AJAY-CUSTOMER` folder.

```powershell
# From AETHERX-Member4-SmartSlot root
docker compose up -d db
cd backend
Copy-Item .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Open `backend/.env` and set a NEW long random `APP_SECRET` (generate one using `py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"`). Do not check `.env` into source control. The demo Docker database uses only local-development credentials.

```powershell
# Still inside backend/
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\python.exe seed_scenarios.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

From another PowerShell tab:

```powershell
cd frontend
npm install
npm run dev
```

Open API docs: <http://localhost:8000/docs>. Open backend readiness: <http://localhost:8000/api/ready>. Open frontend: <http://localhost:5173>.

## 2. Test (run from `backend/`)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

New tests do **not** alter your PostgreSQL demo data; they run with isolated SQLite databases for the Member 4 API tests. The scheduling tests also use SQLite. **You still need to manually verify Alembic migrations and concurrent check-ins/bookings against running PostgreSQL before your hackathon demo**. No real PostgreSQL server was available in the build environment.

## 3. Demo script

A. As customer `demo.booking@aetherx.example`, open My bookings; find a future clinic appointment and QR pass in `backend/demo_output/demo_passes.html` (generated locally). Verify a scan **outside** the opening window fails rather than bypassing safety rules. To show a successful check-in in real time, make a booking within the clinic's check-in window while it is open, then use Admin Check-in. The QR image is a bearer secret; the demo HTML must not be published.

B. As `demo.wait1@aetherx.example`, open `/api/offers` (or customer Queue & Offers screen once integrated). There should be a pending 20-minute offer from a fictional cancelled slot. Accept it; show the new reference and QR. As `demo.wait2@aetherx.example`, explain FIFO: second person gets offered a released slot only if the first declines or times out.

C. As admin `admin@smartslot.demo`, open queue recommendations or evaluate status. Set a professional's presence manually to `break`, and as `demo.late@aetherx.example`, report 40-minute travel ETA. Show the **alert**, not a fraudulent automatic cancellation. For a vacant earlier slot, send a queue-shift offer; customer must accept to move. No-shows require the business grace period and an explicit admin action.

D. Demonstrate error cases: scan the same QR twice (second returns 409); scan another business's QR (404); try to accept another person's waitlist offer (404); send an earlier-slot proposal outside staff working hours (409); try booking a waitlist-held slot (not offered in availability).

## 4. API integration contract

All routes are under `/api`. The `frontend/src/member4-api.ts` file is the recommended client adapter. It reuses the existing `api()` helper and therefore adds `business_id` from session storage and the bearer token automatically. Your teammates only have to import functions from it.

| Role | Method and route | Description |
|---|---|---|
| Customer | `POST /appointments/{reference}/qr/reissue` | Rotate lost QR and return new `qr_token` / `qr_image` |
| Admin | `POST /admin/check-in/preview` | JSON `{ "code": "..." }`; check QR eligibility without mutating booking |
| Admin | `POST /admin/check-in/confirm` | JSON `{ "code": "..." }`; real check-in after preview |
| Customer | `GET /waitlist/mine` | Own waitlist history |
| Customer | `POST /waitlist/{entry_id}/withdraw` | Cancel waitlist entry and give next person the hold |
| Customer | `GET /offers` | Own pending waitlist and queue offers |
| Customer | `POST /offers/{offer_id}/accept` | Transactionally accept a proposed slot |
| Customer | `POST /offers/{offer_id}/decline` | Decline; next FIFO waitlist person gets the slot |
| Customer | `POST /appointments/{reference}/arrival` | JSON: `{"status":"on_the_way","eta_minutes":20}` or `{"status":"arrived"}` |
| Customer | `GET /queue/mine` | Approximate active queue position |
| Admin | `GET /admin/queue/overview?date_on=YYYY-MM-DD` | Per-professional queue, ETA and presence |
| Admin | `GET /admin/queue/recommendations` | Deterministic earlier-slot options |
| Admin | `POST /admin/queue-shift/{reference}?advance_minutes=30` | Make an opt-in offer (default policy: 15m) |
| Admin | `POST /admin/queue-shift/evaluate` | Mark confirmed late/unscanned after grace; flag ETA and absence |
| Admin | `POST /admin/offers/expire` | Expire stale offers and try next FIFO customers |
| Admin | `POST /admin/staff/{staff_id}/presence` | JSON: `{"status":"break"}` or `"on_site"`/`"away"` |
| Admin | `POST /admin/appointments/{reference}/mark-no-show` | Review an *at_risk* booking only after grace period |

The original `GET /admin/check-in/validate?code=` and `POST /admin/check-in?code=` remain temporarily for legacy UI compatibility, but QR token values in query strings can leak via access logs. Integrate the **new JSON-body endpoints** instead.

Base API route `POST /waitlist`, `POST /appointments`, `POST /appointments/{reference}/cancel` and `GET /slots` remain compatible with the existing frontend. All protected endpoints require Bearer demo session and `business_id` query string, except routes identified as public in the existing API. Administrative user in demo: `admin@smartslot.demo`. This is a **passwordless mock login** and must not be deployed publicly.

### Example commands for manual API verification

```powershell
# Login as ADMIN; paste the access_token returned into Swagger's Authorize dialog.
$login = @{role='admin'; name='Demo Admin'; email='admin@smartslot.demo'; business_id=2} | ConvertTo-Json
$auth = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/demo -Body $login -ContentType 'application/json'
$header = @{Authorization="Bearer $($auth.access_token)"}
Invoke-RestMethod -Uri 'http://localhost:8000/api/admin/queue/recommendations?business_id=2' -Headers $header
Invoke-RestMethod -Uri 'http://localhost:8000/api/admin/queue/overview?business_id=2' -Headers $header
```

Check `GET /api/businesses` if IDs differ; seeded business IDs are not a contract. The clinic demo script prints the actual IDs.

## 5. Honest limitations to say to judges

- Arrival ETA is **self-reported**. There is no verified GPS/traffic feed. Tracking via phone requires permission and real integration. Neither a GPS estimate nor a customer pressing “On my way” is proof they will arrive.
- Staff presence is **manual simulation**; no working RFID gate or facial recognition pipeline has been connected. Face recognition would add privacy, bias, spoofing and consent problems; an RFID reader or admin presence button is a safer hackathon MVP.
- Queue suggestions are **deterministic rules** with explainable safety checks, not a trained AI model. Present them as an optimization/scheduling engine, not false AI performance claims.
- A 20-minute offer requires customers to check in-app; push notifications/SMS and an automatic scheduler (Celery/cron) are not yet wired. `/offers` refresh and the admin `/offers/expire` endpoint trigger expiry work.
- The existing demo login grants access based on typed email; robust production identity, rate limiting, privacy controls, outbox/event delivery, concurrency load testing and a PostgreSQL exclusion constraint still need work. Backend correctness on a single test request is not proof of multi-worker production safety.
- Queue position is indicative, **not** a guaranteed service start time. Reassignment still requires customer acceptance; never move a late patient ahead of someone with an earlier appointment without a published fairness policy.

## 6. Integration / merge handoff

**Changed shared backend files (coordinate merges):**

- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/scheduling.py`
- `backend/app/waitlist.py`

**New files (mostly safe to add):**

- `backend/app/queue_engine.py` + `backend/app/timeutil.py`
- `backend/migrations/versions/0003_member4_queue.py`
- `backend/tests/test_member4_flow.py`
- `backend/seed_scenarios.py`
- `frontend/src/member4-api.ts`
- `MEMBER4-START-HERE.md`

**Do not blindly overwrite another developer's `main.py` or SQLAlchemy models.** Merge Member 4 commits before Ajay and Admin integrate; then run migrations + all tests together. The queue module depends on the existing multi-industry migration `0002_multi_industry`.

## 7. Prioritized future work

First integrate the customer offer cards and admin scanner with the adapter and run a live Postgres demonstration. Next add a periodic offer expiry job, admin confirmation for absent staff, real-time updates (SSE/WebSocket), and monitoring/audit events. Finally, if time permits, build an **optional opt-in** GPS ETA provider (with a permissions/privacy plan) and a queue optimization simulation with measured success criteria. Do not start with biometric recognition.
