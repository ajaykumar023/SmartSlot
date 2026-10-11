> **2026 GeoSmart update:** See [GEOSMART-AUTO-ALLOCATION-START-HERE.md](GEOSMART-AUTO-ALLOCATION-START-HERE.md) for GPS ETA, QR-pass library, service toggles, auto-allocation, alerts, migration, and safety limitations.

# SmartSlot

**Team Aetherx Member 4 backend extension:** see [MEMBER4-START-HERE.md](MEMBER4-START-HERE.md) for implemented QR, waitlist, queue and testing changes, with a Windows runbook and merge instructions. This branch deliberately does not modify teammate-owned UI pages.

**Smart Check-In. Smarter Scheduling.** SmartSlot is an appointment booking and check-in demo for four fictional businesses: a salon, clinic, repair center, and consulting practice. Customers select a business, browse its services, book a qualified professional, receive a QR pass, and review offers. Admins manage appointments and check-in within their signed business access. The Best-Fit Slot Finder is deterministic rule-based scheduling logic.

## Stack and limits

- React + Vite + TypeScript + Tailwind CSS frontend
- Python + FastAPI + Pydantic backend
- PostgreSQL + SQLAlchemy 2.x + Alembic
- QR passes use an opaque random token; only its SHA-256 hash is stored
- No payments, clinical features, GPS, trained AI, external real-time integrations, or production authentication
- In-app notification and delay behavior is simulated and labelled

## Requirements

Node.js 20+ and npm, Python 3.11+, and Docker Desktop with Compose (or a native PostgreSQL 14+ installation). SQLite is not supported. Commands below are for Windows PowerShell from the repository root.

## Start PostgreSQL (Docker)

```powershell
docker compose up -d db
docker compose ps
```

The local demo database is `smartslot` on port `5432`, user/password `smartslot`. These credentials are for local development only. To stop it, use `docker compose down`; add `-v` only when you intend to delete the local database volume.

For native PostgreSQL, create a database and login role named `smartslot` with a local development password, then set `DATABASE_URL` in `backend/.env` to the matching `postgresql+psycopg://...` connection string. Check the service with `pg_isready -h localhost -p 5432`.

## Start the API

```powershell
Copy-Item .env.example backend/.env
# Edit backend/.env and replace APP_SECRET with a long random value.
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
python seed.py
uvicorn app.main:app --reload --port 8000
```

PowerShell execution policy may block activation; use `Set-ExecutionPolicy -Scope Process Bypass` in that terminal, then activate again. Alternatively call `.venv\Scripts\python.exe -m pip ...` and `.venv\Scripts\uvicorn.exe ...` without activation. Alembic and seed commands run from `backend/`.

## Start the frontend

Open a second PowerShell terminal at the repository root:

```powershell
cd frontend
npm install
npm run dev
```

The frontend defaults to `http://localhost:5173`; API defaults to `http://localhost:8000/api`. To change the API URL, create `frontend/.env.local` with `VITE_API_BASE_URL=http://localhost:8000/api` (`VITE_API_URL` is also accepted for compatibility). To change ports, pass Vite `--port <port>` and Uvicorn `--port <port>`, then update `CORS_ORIGINS` in `backend/.env` and the frontend API URL as needed.

## Demo sign-in

Open `http://localhost:5173` and choose one of the four seeded businesses. Customer demo accepts a chosen name/email; use the same email to access those bookings. Admin demo uses `admin@smartslot.demo`. Sessions are signed bearer tokens that expire after 24 hours. Business selection is stored in the current browser session; server-side claims enforce access. This is a role-switching demo, not a password-based identity system.

## Migrations, seed, tests, and build

From `backend/`, repeatable local commands are:

```powershell
alembic upgrade head
python seed.py
python -m pytest
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Reset the demo data by stopping services, removing the `smartslot_pg` Docker volume with `docker compose down -v`, then starting PostgreSQL and running migrations and seed again. This deletes the local demo database.

## Troubleshooting and production

- If PostgreSQL refuses a connection, check `docker compose ps`, `docker compose logs db`, port 5432 conflicts, and that `DATABASE_URL` matches the configured role/database.
- If API startup reports an import error, activate the backend virtual environment and install `requirements.txt` there.
- CORS errors usually mean the frontend URL is absent from comma-separated `CORS_ORIGINS`.
- Use a production secret manager for `APP_SECRET` and database credentials. Do not expose the local Compose credentials or use the seeded demo identities in production. Configure HTTPS, real identity, rate limiting, backups, and operational monitoring before public deployment.

## Known limitations

- Four seeded fictional businesses are available. Business onboarding and arbitrary tenant creation are not exposed in the demo UI.
- Service creation and business-hour editing are available through the API. Staff qualification management and blocked-time editing are not exposed in the current UI.
- Basic queue position estimates and opt-in earlier-slot rescheduling are now implemented by Member 4. Notifications are still in-app simulated, and external SMS/email is not implemented.
- Member 4 waitlist offers are matched to FIFO customers by released appointment date, service and staff-feasible time; time-limited offer holds are respected. Queue-shift suggestions use explainable rules and do not use a live traffic feed.
- QR pass is shown on booking confirmation and kept in the current tab session. The raw QR secret is intentionally not stored by the server; Member 4 adds an authenticated QR reissue endpoint and the admin-only booking-reference fallback.
- No exclusion constraint is installed; booking serialization relies on a staff-row lock and a second availability check in PostgreSQL.
- In this authoring sandbox, the production frontend build and preview work, but `npm run dev` dependency optimization is blocked when esbuild tries to traverse a parent directory outside the allowed workspace. Run the dev command in a normal local terminal if you need hot reload.
- PostgreSQL/Docker were unavailable here, so connection readiness, applying the migrations, inserting seed records, and PostgreSQL-backed booking flows remain unverified. Scheduling unit tests use an isolated in-memory SQLite database; the application runtime still requires PostgreSQL.

See [architecture](docs/architecture.md) and [demo script](docs/demo-script.md). API docs are at `/docs` while FastAPI is running.
