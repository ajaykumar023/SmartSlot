# SmartSlot — refined UI + appointment-day QR passes

This patch is based on the last `AETHERX-GPS-AutoAllocator-Full.zip` snapshot. It updates **actual React/FastAPI source**, not a mock image. Your teammate's local edits are not automatically merged by ZIP extraction: back up the project before overwriting changed files.

## What changed

- A calmer, product-like design: restrained green/neutral palette, flatter controls, simpler app navigation, a workspace selector, and a redesigned receptionist overview.
- Customer **QR passes** now lists upcoming appointments as compact visit cards.
- The appointment pass popup shows booking details. On a future day, the QR remains locked. There is an explicit **Simulate appointment day** action: it shows a VISUAL MOCK that **cannot be scanned or used to check in**. It does not change time, generate a real token, or alter the database.
- On the actual appointment day (determined by the *business timezone* on the server), **Show my check-in QR** calls the new authenticated `POST /api/appointments/{reference}/qr/activate` endpoint. It rotates the token, revoking any older code. The same browser tab/session caches the QR image so a normal reopen does not rotate the token again. A new browser session may issue another token, invalidating previous copies; customers should use the latest pass.
- `GET /api/appointments/{reference}/qr/status` checks pass readiness without issuing a token. The older `/qr/reissue` route also rejects requests before appointment day.
- Booking/auto-book/waitlist acceptance no longer returns real QR image secrets for a **future date**. Booking confirmation still appears and directs the customer to QR passes; accepting a waitlist offer still navigates to confirmation even without an immediate QR.
- Fixes the `os` import in `backend/app/main.py` that previously caused FastAPI test lifecycle errors.

## Install on your Windows laptop

1. Stop FastAPI and Vite (`Ctrl+C`) and **back up** `D:\AETHERX-Member4-SmartSlot` first, especially work modified by team members.
2. Extract `AETHERX-UI-Pass-Day-Update.zip` *into* `D:\AETHERX-Member4-SmartSlot` preserving the `backend` and `frontend` subfolders. There should be only one `frontend` and one `backend` directory.
3. This update has **no new Alembic migration**. It uses your existing PostgreSQL database unchanged.
4. In PowerShell terminal one:

```powershell
cd D:\AETHERX-Member4-SmartSlot\backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

5. In terminal two:

```powershell
cd D:\AETHERX-Member4-SmartSlot\frontend
npm ci
npm run build
npm run dev
```

6. Open http://localhost:5173. Log in as customer, choose **QR passes**, and open an appointment pass. For a future appointment, click **Simulate appointment day** to show a **non-scannable demo preview**; click Back to return. Real QR activates automatically *as an available action* on the actual booking day when you open the pass.
7. Open admin **Overview** for the new reception-focused page, and verify Check-in Desk still opens and processes valid day-of-appointment QR passes **within** the configured check-in window.

## Test status and safeguards

- Local Python test suite: **35 passed**, using an isolated SQLite test database.
- All changed TSX files were parsed successfully using the TypeScript parser; **the full frontend build could not be executed here** because npm package installation was incomplete. `npm run build` on your laptop is required before calling this validated end-to-end.
- No live Google Maps integration changes and no cross-branch automatic rescheduling changes are included in this UI patch.
- This project still uses passwordless **demo authentication** and is not suitable for real customer records without production authentication, security review, rate limiting, concurrency testing on PostgreSQL, and strict data handling.

## Endpoint examples (with normal bearer auth and `business_id`)

`GET /api/appointments/SS-XXXXXX/qr/status` returns `available`, `reason`, `opens_at`, `check_in_opens_at`.

`POST /api/appointments/SS-XXXXXX/qr/activate` issues a new QR only when appointment day has begun at the business location, the booking is confirmed/at-risk, and the appointment has not ended.

**Important:** QR issuance is not the same as check-in permission. Reception still enforces the shorter check-in window (such as 30 minutes before start).
