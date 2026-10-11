# AETHERX / Member 4 — GPS, QR passes, services, auto allocator & alerts

This package extends **AETHERX-Admin-QR-Full-Project** (the previously delivered project). It is **a demo development implementation**, not deployment-ready patient/appointment software.

## What is now implemented

| Customer | Reception / admin | Backend |
| --- | --- | --- |
| **QR Passes** page; secure lost-pass reissue and PNG save | Toggle services Active/Inactive | Reuses `PATCH /api/admin/services/{id}`; no existing bookings deleted |
| **On my way · GPS** with permission, stop button, 60s ETA refresh, OSM location preview and Google Maps directions | Configure destination latitude/longitude under Business Settings | `POST /api/appointments/{ref}/travel-eta`; Google Routes with server-side key; no customer coordinates persisted |
| **Auto-allocate best available** on chosen date | **Auto-Allocator & Alerts** page with unread alerts, acknowledge, manual sweep | Background 60s sweep of expired and released slots, FIFO eligibility + conflict checks |
| Booking confirmation now has a **Save QR pass** link | Browser auto-refresh of admin alerts every 30 seconds | Auto staff assignment considers earliest feasible time, qualifications, staff workload and reported absence |

**Not yet included:** automatic cross-branch transfers, autonomous rescheduling of an existing confirmed booking, push notifications when the admin screen is closed, calibrated ML models, production authentication, or tested concurrent multi-server operation.

## Install — Windows PowerShell

1. **Back up your project** before replacing files; `main.py`, `App.tsx`, `Admin.tsx`, and `Customer.tsx` may contain teammate changes. Extract the **update ZIP** over `D:\AETHERX-Member4-SmartSlot`, preserving `backend/` and `frontend/` structure. Check folder structure: `D:\AETHERX-Member4-SmartSlot\backend\app\geosmart_api.py` must exist.
2. Keep Docker Desktop open, then in VS Code terminal at project root:

   ```powershell
   docker compose up -d db
   cd backend
   # IMPORTANT: do not overwrite an existing backend/.env
   notepad .env
   ```

3. Add these variables to your **existing** `backend/.env` (never put your private Google key in `frontend`):

   ```env
   GOOGLE_ROUTES_API_KEY=
   AUTO_ALLOCATOR_ENABLED=true
   AUTO_ALLOCATOR_INTERVAL_SECONDS=60
   ```

   Leave the Google key empty initially: it runs a clearly labeled **straight-line demo ETA**, not live road traffic. With a Google Cloud billing-enabled project, enable **Routes API** and put its restricted server-side key in `.env`. Google charges for traffic-aware calls, so set quota caps.

4. Apply database migration once **before starting the app**:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic upgrade head
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
   ```

   If you've been running the app, stop Uvicorn with Ctrl+C first. The new migration is `0004_geosmart_automation`. **Do not run seed.py again** unless you explicitly intend to add/reset seed records; existing bookings stay intact with this migration.

5. Second terminal:

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot\frontend
   npm run build
   npm run dev
   ```

   Open `http://localhost:5173`.

## Use the features

- **Admin → Services**: activate/deactivate a service. Inactive services disappear from the customer catalog and cannot receive new bookings; previously confirmed appointments remain.
- **Admin → Settings → GPS destination**: set *real* destination latitude/longitude for the demo business. Use valid values. For a **fictional Bengaluru demo**, `12.9716,77.5946` are example coordinates only; don't imply they are the clinic's true position.
- **Customer → On my way · GPS**: choose appointment (eligible from two days before to end of appointment), permit browser GPS, see the map and ETA. Browsers generally require **localhost or HTTPS** for geolocation. If accuracy exceeds 250m, the backend asks to retry. You can stop tracking at any time.
- **Customer → QR passes**: choose an active booking, generate a **replacement** QR if necessary and **save** the PNG. The original QR cannot be retrieved (only its hash exists); reissue invalidates earlier codes. Original pass can also be saved from the booking confirmation page.
- **Customer → Book a service → Auto-allocate**: choose service, date, name and signed-in email; the engine selects earliest feasible appointment and qualified staff, avoiding anyone's existing booking. The confirmed appointment is returned with its QR.
- **Admin → Auto-Allocator & alerts**: inspect and acknowledge alerts, or manually run a sweep for demo. Normally a sweep happens every 60 seconds while Uvicorn is running. Customers get in-app messages for released-slot offers and booking confirmations. Actual waitlist booking still requires the recipient to accept the offer.

## API routes

| Method | Route | Access |
| --- | --- | --- |
| GET | `/api/businesses/{id}/location` | Demo business public catalog |
| PUT | `/api/admin/location?business_id=N` | Admin |
| POST | `/api/appointments/{reference}/travel-eta?business_id=N` | Booking owner |
| POST | `/api/appointments/auto-book?business_id=N` | Customer |
| GET | `/api/admin/alerts?business_id=N` | Admin |
| POST | `/api/admin/alerts/{id}/read?business_id=N` | Admin |
| POST | `/api/admin/automation/run?business_id=N` | Admin |
| PATCH | `/api/admin/services/{id}?business_id=N` | Admin, **already in previous backend** |

## Correctness and safety boundaries

- **Real traffic ETA**: only when Google Routes key works. A Google request failure returns `503` (not a fake successful traffic ETA). Without key, data is labeled `demo_straight_line` and is **not used for automatic rescheduling**. No customers are silently transferred to another business.
- **No-show logic**: a GPS prediction or a missing on-the-way signal never releases a booking; staff must verify a no-show using the existing flow. Offers temporarily hold released slots.
- **Auto-allocation**: the current algorithm is **deterministic and explainable, not a machine-learning model**. It automatically assigns a staff member to a new appointment and makes time-limited offers to waitlisted customers for safely released slots; it does not autonomously transfer confirmed visits between branches.
- **Privacy**: exact customer coordinates are never persisted by SmartSlot's backend. The customer explicitly starts/stops live GPS. Maps (OpenStreetMap) and routing providers (Google when enabled) receive coordinates to perform those services. Never share the Google API key publicly.
- **Authentication**: existing `/auth/demo` identifies users by entered email and is deliberately **not secure enough for real customer or healthcare use**.
- **Notifications**: admin alerts are persisted and the admin page polls every 30 seconds. They are **not** SMS, email, or background OS push notifications.
- **Concurrency**: SQLite tests cover logic but not PostgreSQL parallel-worker reservation guarantees. For production, add a Postgres exclusion constraint on staff/time ranges, proper user authentication, per-organization rules, and a single durable job queue rather than one sweeper per Uvicorn worker.

## Verification performed

- Python suite: **33 passed** with SQLite, `AUTO_ALLOCATOR_ENABLED=false` for test isolation.
- React changed TSX files: syntax parsing checked.
- **Full Vite/TypeScript build not verified in the sandbox**: npm registry was unavailable. Run `npm run build` locally and send any errors.
- PostgreSQL migration and Google Routes API are not live-tested in the sandbox.
