# AETHERX SmartSlot — Admin QR and reception upgrade

This package is an update for your existing `D:\AETHERX-Member4-SmartSlot` project. **Extract it into that folder**, NOT into `backend` or `frontend` separately. Back up any teammate-edited files before replacing them.

## Fixes the startup ImportError

Your local backend reported:

`ImportError: cannot import name 'delay_recommendations' from 'app.queue_engine'`

Your `main.py` already expects the later-slot suggestion function. This update includes a matching `backend/app/queue_engine.py` which defines `delay_recommendations`. **Do not remove the import in main.py**; that would break the delay-recovery routes.

After extracting, open **a new VS Code PowerShell terminal**:

```powershell
cd D:\AETHERX-Member4-SmartSlot\backend
Select-String -Path .\app\queue_engine.py -Pattern '^def delay_recommendations'
.\.venv\Scripts\python.exe -c "from app.queue_engine import delay_recommendations; from app.main import app; print('Imports OK:', app.title)"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

You should see a definition match and an `Imports OK: SmartSlot API` line. If you already have a Uvicorn terminal open, stop it with Ctrl+C before the last command. Leave the running backend terminal open.

## Start frontend (second VS Code terminal)

```powershell
cd D:\AETHERX-Member4-SmartSlot\frontend
npm run build
npm run dev
```

If the build reports an error, copy the complete terminal output. The frontend was syntax-checked against TypeScript but a full npm build could not be completed in the packaging environment.

## What changed

**Admin > Appointments** (`http://localhost:5173/admin/appointments`)
- Search and status filter, summary counts for currently displayed rows, responsive appointments table.
- **View details** modal with name, service, doctor, scheduled time, and booking status.
- **Open check-in desk** sends the reference to reception.
- Does **not** reveal stored QR secrets to an admin.

**Admin > Check-in desk** (`http://localhost:5173/admin/check-in`)
- Camera QR scanning or manual reference entry.
- Two-step preview followed by explicit confirmation.
- Manual reference check-in requires a receptionist's identity-verification checkbox.
- Today's expected/checked-in/at-risk counts and arrivals list.
- Uses backend `POST /api/admin/check-in/preview` and `POST /api/admin/check-in/confirm` with a JSON body, not query-string QR secrets.
- Status, duplicate scan, early check-in and expiration are still enforced by backend.

**Customer > My bookings** (`http://localhost:5173/bookings`)
- **QR pass** popup can generate a *replacement* QR pass when lost.
- The original QR is NOT recoverable from the backend. Issuing a replacement makes the old one invalid immediately.
- Clicking the popup does not rotate the pass until the customer explicitly confirms replacement.

**QR alignment** is centered on the booking confirmation page.

## How to test without a future-check-in false alarm

Use a booking whose time is inside the business' actual check-in window. A booking created for next week is supposed to fail check-in. A duplicate QR or a previously rotated QR should fail. Do not modify your machine clock to force a test; a separate mock-time demo mode would be safer.

## Files included in the update

- `backend/app/queue_engine.py` (corrected import compatibility)
- `frontend/src/pages/Admin.tsx`
- `frontend/src/pages/Customer.tsx`
- `frontend/src/pages/ReceptionDesk.tsx` (new)
- `frontend/src/components/AppointmentDetailsModal.tsx` (new)
- `frontend/src/components/CustomerPassModal.tsx` (new)
- `frontend/src/member4-api.ts`
- `frontend/src/admin-upgrade.css` (new)
- `frontend/src/main.tsx` (adds the CSS import)

This update does NOT change `main.py`, the database migrations, or your `.env`. The API endpoints used here already exist in the latest AETHERX Member 4 backend.

## Verification in this environment

- 28 Python backend tests passed with an isolated SQLite test database.
- 17 TypeScript/TSX files parsed with zero syntax errors.
- PostgreSQL concurrency and a complete Vite production build need verification on your Windows setup.

## Safe merge for teammates

These frontend edits touch Admin, Customer and the entry stylesheet. If teammates have made changes to those same files, **diff/merge rather than overwrite**. The backend fix can be applied by itself using the small startup-fix ZIP.
