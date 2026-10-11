# AETHERX SmartSlot — Phase 4: Universal Service Intake (backend only)

This patch generalizes the prior haircut-only preferences feature into optional **appointment-level intake** for every business category currently supported in SmartSlot:

| Business category | Intake prompts supplied by backend |
|---|---|
| `salon` | Desired haircut/style/treatment, preferred length, reference look/instructions |
| `clinic` | General reason for visit, first/follow-up, accessibility arrangements |
| `repair_center` | Device/item, model, reported issue |
| `consultant` | Consultation goal, project context, questions |

Each booking can include optional `service_intake` with `summary`, `notes`, and `answers`. Backend validates answers against the category's allowed field IDs. **This does not change appointment duration, service price, staff qualifications, medical decisions, or recovery policy.** Intakes follow the appointment ID when Phase 2 changes staff or moves between branches.

## Contents and dependencies

Backend changes only:

- `backend/app/service_intake_api.py`: generic template, customer GET/PUT, admin briefing
- `backend/app/service_intake_schemas.py`: input validation
- `backend/app/main.py`, `backend/app/models.py`, `backend/app/schemas.py`: booking and auto-book integration, ORM and request types
- `backend/migrations/versions/0008_general_service_intake.py`: additive migration
- `backend/tests/test_service_intake.py`: integration and migration tests

**Requires Phase 3 installed** with migration `0007_haircut_preferences` (plus Phase 1 and 2 migrations). Phase 4 revision is `0008_general_service_intake`. The legacy salon-only `haircut_preferences` request and API are intentionally kept for compatibility, but new forms should use `service_intake`. A unified briefing displays prior haircut notes when the new intake is absent. Avoid editing old and new fields simultaneously; the new generic intake takes precedence in its briefing.

**No frontend code, `.env`, map keys, QR logic, or TomTom code is modified.**

## Install safely — Windows PowerShell

1. Stop FastAPI. Copy your working project folder somewhere safe, especially any teammate-edited backend files.
2. Back up live PostgreSQL **before** running migration. From project root:

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot
   docker compose up -d db
   docker compose exec db pg_dump -U smartslot -d smartslot -Fc -f /tmp/smartslot_before_phase4.dump
   docker compose cp db:/tmp/smartslot_before_phase4.dump .\smartslot_before_phase4.dump
   ```

   Keep the backup offline, out of GitHub.
3. Extract `AETHERX-Universal-Service-Intake-Backend-Update.zip` to `D:\AETHERX-Member4-SmartSlot`, preserving the `backend/` folder. Merge any conflicting edits; do not blindly overwrite teammate changes.
4. In the backend terminal:

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot\backend
   .\.venv\Scripts\python.exe -m alembic current
   .\.venv\Scripts\python.exe -m alembic upgrade head
   .\.venv\Scripts\python.exe -m alembic current
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
   ```

   Expect revision `0008_general_service_intake` after successful migration. **Do not `alembic stamp` around errors.** If `0007` is missing, install Phase 3 first. If PostgreSQL rejects the migration, stop and share the error rather than altering database history.
5. Verify the new database table from project root:

   ```powershell
   docker compose exec db psql -U smartslot -d smartslot -c "\d booking_service_intakes"
   ```

6. Open http://localhost:8000/docs and find **Service Intake (All Industries)**.

## New API endpoints

- `GET /api/businesses/{business_id}/intake-template?service_id=...` — public, returns category-specific fields for that service; no private booking data.
- `POST /api/appointments?business_id=...` — existing booking endpoint, optionally accepts `service_intake`.
- `POST /api/appointments/auto-book?business_id=...` — existing auto-booking endpoint, optionally accepts `service_intake`.
- `GET /api/appointments/{reference}/service-intake?business_id=...` — customer owner reads existing intake (supports legitimate post-transfer sessions).
- `PUT /api/appointments/{reference}/service-intake?business_id=...` — owner replaces intake before appointment begins.
- `GET /api/admin/appointments/{reference}/service-briefing?business_id=...` — admin authorized for the appointment's **current** branch reads details and intake.

All fields are optional. Unknown field IDs or unsupported photo-upload fields produce HTTP 422. Maximums: summary 160 characters, notes 1200, at most 8 answers of up to 300 characters each. PUT is a **full replacement**, not a partial patch. JSON `answers` are stored in a new `booking_service_intakes` table keyed by `appointment_id`.

Use a demo customer Bearer token from `/api/auth/demo` in Swagger to book; use demo admin token for the service briefing.

## Examples (replace IDs and dates with your real demo records)

### Salon

```json
{"service_id": 1, "starts_at": "2026-10-21T10:30:00+05:30", "name": "Test User", "email": "test@example.com", "service_intake": {"summary": "Low taper fade", "notes": "Please ask before cutting the fringe", "answers": {"desired_style": "Low taper", "preferred_length": "medium", "reference_description": "Keep volume on top"}}}
```

### Clinic

```json
{"service_id": 4, "starts_at": "2026-10-21T11:00:00+05:30", "name": "Test User", "email": "test@example.com", "service_intake": {"summary": "General consultation", "answers": {"visit_reason": "Routine consultation", "visit_type": "First visit"}}}
```

### Repair center

```json
{"service_id": 8, "starts_at": "2026-10-21T12:00:00+05:30", "name": "Test User", "email": "test@example.com", "service_intake": {"summary": "Laptop display inspection", "answers": {"item_type": "Laptop", "model": "Model 2020", "reported_issue": "Screen flickers intermittently"}}}
```

### Consultant

```json
{"service_id": 12, "starts_at": "2026-10-21T14:00:00+05:30", "name": "Test User", "email": "test@example.com", "service_intake": {"summary": "Product strategy discussion", "answers": {"consultation_goal": "Validate launch plan", "project_context": "Building a prototype", "questions": "How should we prioritize features?"}}}
```

**All service and business IDs, dates, and availability are illustrative.** Client login email must match the booking email. More fields for any category can be added to `CATEGORY_FIELDS` in `service_intake_api.py`; business-specific configurable templates are a future feature.

## What remains unfinished — important

- **Not production-safe for private patient information**: current passwordless demo accounts and broad demo-admin access do not provide verified identities or real clinic privacy controls. Enter only fictional/test data; don't collect diagnoses, patient records, passwords, medical photographs, etc. A secure product needs verified authentication, role-specific access, encryption/security review, retention/deletion policy and appropriate legal compliance.
- No reference photo upload, file storage, AI interpretation, or dynamic form-building UI yet.
- This intake is **not** used to override staff qualifications, slot duration, or auto-recovery matching. Those rely on authoritative business records. The intake is passed to the assigned professional via the briefing API.
- Full PostgreSQL concurrent double-booking protection, real TomTom integration and live database migration are not proven by the SQLite unit/integration suite.
- Automated tests here passed **79/79** in isolated SQLite with no live TomTom calls. Run the commands above on your own environment.

After the backend migration succeeds, the next front-end step will be to retrieve the intake template per selected service and render optional fields. Until then, this functionality is available through FastAPI Swagger.
