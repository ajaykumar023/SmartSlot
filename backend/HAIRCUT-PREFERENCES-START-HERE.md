# AETHERX SmartSlot — Haircut Consultation Backend (Phase 3)

## What this patch does

**Backend + PostgreSQL migration only** — no frontend files and no `.env` files.

1. Salon customers can submit an optional `haircut_preferences` object **while booking normally or with auto-booking**.
2. A customer may **GET or PUT** haircut preferences on an existing upcoming appointment.
3. An authorized demo admin can fetch a **read-only stylist briefing** for the appointment at its **current branch**.
4. Preferences are stored by **`appointment_id`**, not by staff or branch. They follow the same appointment when Phase 2 Smart Recovery reassigns a barber or transfers a booking to another branch.
5. Existing bookings without a preference record continue to work. Other business categories (clinics, repair centers, consultants) reject salon haircut preferences.
6. Free-text notes are limited to 800 characters and exposed only on booking-scoped API endpoints, not the public services or slots endpoints.

### What it intentionally does NOT do

- **No reference-photo upload yet.** Secure private image storage, download authorization, deletion and retention must be designed before storing customers' photos. Unsupported `reference_image_url`/`reference_image_path` request fields produce a validation error.
- **No trained AI, image recognition, LLM summarization, or barber-specialty classifier.** Customer descriptions are stored as notes. Scheduling still trusts configured `staff_services` qualifications, not words in a customer request.
- **No verified user accounts.** Existing `/api/auth/demo` allows passwordless demo customer logins and a shared admin identity with access across demo businesses. Suitable ONLY for a hackathon development environment. Do not put genuine customer descriptions or private images into a public installation until authentication is replaced.
- **No automatic SMS/email**, or notification delivery to the barber; admins retrieve the briefing through the API for now.
- Does not solve Phase 2's outstanding PostgreSQL concurrency / database-level exclusion constraints.

## Prerequisite

Install **Backend Phase 1 + Phase 2** first. Alembic should be at revision `0006_smart_recovery` before Phase 3, or `alembic upgrade head` will migrate through earlier revisions if those migration files are present. The new migration is **`0007_haircut_preferences`**.

## Install (Windows PowerShell)

1. Stop your running FastAPI server with `Ctrl+C` and **back up any existing modified backend files**.
2. Back up your PostgreSQL database. From `D:\AETHERX-Member4-SmartSlot`:

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot
   docker compose exec db pg_dump -U smartslot -d smartslot -Fc -f /tmp/smartslot_before_haircut.dump
   docker compose cp db:/tmp/smartslot_before_haircut.dump .\smartslot_before_haircut.dump
   ```

   Store the backup outside GitHub. Substitute your own credentials if different.

3. Extract `AETHERX-Haircut-Preferences-Backend-Update.zip` **directly into** `D:\AETHERX-Member4-SmartSlot`, preserving the `backend/` file paths. It overwrites `backend/app/main.py`, `models.py`, and `schemas.py`, adds `haircut_api.py` / `haircut_schemas.py`, and adds the migration and tests. Merge carefully if teammates edited the same files.
4. Run these in your backend terminal:

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot\backend
   .\.venv\Scripts\python.exe -m alembic current
   .\.venv\Scripts\python.exe -m alembic upgrade head
   .\.venv\Scripts\python.exe -m alembic current
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
   ```

   Expect `0007_haircut_preferences` as the current migration. Our isolated environment passed **69/69 tests** against SQLite; your real PostgreSQL installation still needs verification. If Alembic reports that revision 0006 is missing, **do not stamp the database**: install the previous Phase 2 migration file before continuing.

5. Open http://localhost:8000/docs and find the **Haircut Consultation** section.

## Backend request examples

Use an existing salon `business_id` and **customer demo** Bearer token from `POST /api/auth/demo` in Swagger's `Authorize` interface (see existing project guide). Never post your real key/token online.

### 1. Book and describe a haircut in one request

`POST /api/appointments?business_id=1` (or `POST /api/appointments/auto-book?business_id=1` with the normal date-specific fields)

```json
{
  "service_id": 1,
  "starts_at": "2026-10-21T10:30:00+05:30",
  "name": "Demo Customer",
  "email": "demo@example.com",
  "haircut_preferences": {
    "style": "taper",
    "preferred_length": "medium",
    "notes": "Low taper, keep the volume on top, don't shorten the fringe."
  }
}
```

The booking date, IDs and login email must reflect YOUR existing salon records. The sample date is illustrative, not a known available appointment.

### 2. Edit the description for an already booked appointment

`PUT /api/appointments/{reference}/haircut-preferences?business_id=1`

```json
{
  "style": "fade",
  "preferred_length": "short",
  "notes": "Low skin fade; leave the fringe slightly longer."
}
```

**GET** the same route to inspect. The update is a *full replacement*: omitted fields reset to their defaults. Editing is permitted only before a confirmed/at-risk appointment starts.

### 3. Stylist/reception briefing

Use a **demo admin** Bearer token:

`GET /api/admin/appointments/{reference}/stylist-briefing?business_id=1`

Returns the customer name, current professional, service, existing service duration, start time and preferences. Customer email is deliberately omitted. When a recovery event transfers the appointment, the briefing becomes available under the **destination** branch instead.

### Accepted styles and lengths

- `style`: `fade`, `taper`, `trim`, `buzz_cut`, `layers`, `styling`, `other`, or `not_sure`.
- `preferred_length`: `short`, `medium`, `long`, or `unsure`.
- `notes`: plain text, maximum 800 characters.

## PostgreSQL verification

From the project root:

```powershell
cd D:\AETHERX-Member4-SmartSlot
docker compose exec db psql -U smartslot -d smartslot -c "\d booking_haircut_preferences"
```

`booking_haircut_preferences.appointment_id` is the primary key and refers to `appointments.id`. The foreign key cascade removes preferences if an appointment record is deleted. Normal cancellations keep the original appointment/history and associated notes for now; production retention and deletion rules still need to be designed.

## Suggested next milestone

Once the migration and Swagger APIs run on PostgreSQL, add **barber specialty tags and salon-validated qualifications**, then let Smart Recovery filter available stylists by configured specialty as well as service qualifications. This should be an explicit salon-admin setting, not automatic inference from unstructured customer prose. After this, create private reference-photo upload with verified customer identity and deletion/retention controls, and finally build the React input and briefing panels.
