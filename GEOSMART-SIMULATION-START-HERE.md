> **Latest update:** The default Simulation Lab now demonstrates *automatic cross-branch rerouting without per-transfer acceptance*. See [AUTO-REROUTE-START-HERE.md](AUTO-REROUTE-START-HERE.md). This older guide describes the still-available legacy limited-delay workflow.

# AETHERX SmartSlot — Limited Delay Recovery + Customer Simulation Lab

## What changed

This release adds a **safe, functional preview of limited postponements**. Customers can be offered a later appointment **15 or 30 minutes** after their original booking if:

- Their self-reported arrival is predicted **outside** the business grace period.
- Appointment start is within the next **3 hours**, and there is time to react.
- The proposed start leaves **at least five minutes** before arrival.
- The original professional is qualified, working, and free; service and buffer do not collide with any other customer.
- The time is not already held by another active offer.
- The customer **explicitly accepts** a five-minute offer. Prior to acceptance, their original booking stays reserved.

The late customer's own booking is updated through `POST /api/offers/{offer_id}/accept`. The QR token still belongs to that booking and uses the updated check-in window. Confirmed neighbors never move automatically.

**No Google Maps or actual live GPS is connected.** ETA is customer-reported for the production endpoint, and 100% fictional in the simulation.

## Simulator in the running app

1. Extract `AETHERX-GeoSmart-Simulation-Update.zip` at **`D:\AETHERX-Member4-SmartSlot`**, preserving `backend/` and `frontend/` directories, allowing replacements. If anyone edited these files after our last handoff, take a backup or use the diff first.
2. Your existing backend and frontend terminals run with **reload**. If needed, restart:
   - Backend from `backend`: `\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`
   - Frontend from `frontend`: `npm run dev`
3. Browser: `http://localhost:5173`
4. **Switch role → Admin**, using your seeded `admin@smartslot.demo` account. Prefer the *Northstar Family Clinic* business.
5. In the admin sidebar click **Simulation Lab** (or navigate to `http://localhost:5173/admin/simulation`).
6. Choose scenarios and adjust the simulated traffic slider:
   - **Traffic jam + opening:** default +25 min traffic. Rahul is expected at **10:15**, moved to **10:30** if he accepts; Priya's 11:15 and Arjun's 11:50 stay untouched. Meera receives a *simulated* waitlist offer for 10:00.
   - **Fully booked doctor:** same delay, but 10:30 is occupied. No reassignment within 30 min; trigger staff review.
   - **Small traffic delay:** default +3 min traffic. Rahul is expected at **09:53**, keeps the original 10:00 booking.
7. Click **Simulate Rahul accepting**, **Simulate declining**, **Reset decision**. These actions call the read-only backend simulator and **never alter PostgreSQL records**.

The simulation is illustrative of policy and decision logic; it does not prove the external traffic ETA nor update real bookings. All timestamps on its sample board are fictional clinic-clock times.

## Backend API — REAL limited delay request (live database)

The following endpoints **do** use real appointments and customer access checks, but only accept self-reported ETA. You can call them from your teammate's frontend later.

### Preview feasible times

`POST /api/appointments/{reference}/delay-options?business_id={id}` (customer JWT required)

```json
{"eta_minutes": 45, "max_delay_minutes": 30}
```

Returns available 15/30 minute later options **only for appointments starting within 3 hours**. Does not modify the booking.

### Create a temporary offer

`POST /api/appointments/{reference}/delay-request?business_id={id}` with the same body and customer JWT.

Creates a five-minute `delay_shift` offer to the same customer. Does not alter the booking until the owner calls existing `POST /api/offers/{id}/accept`; declined and expired offers retain original booking. Existing `GET /api/offers` shows these new kinds of offers in Queue & Offers.

### What is *not* complete

- **Automatic offer of the vacated original time to waitlisted customers** after a real delay is not implemented yet. After a delay is accepted, the old time is available for ordinary booking; the Simulation Lab shows how a waitlist offer would work, not a real automated handoff.
- Customer My bookings has no integrated **Running late?** button yet: wire the preview/request endpoints with your UI teammate. The existing Queue & Offers page can *accept* the delay offer.
- No Google Maps API key, device geolocation, branch coordinates, cross-branch transfers, push notifications, live GPS, traffic predictions or calibrated arrival confidence.
- PostgreSQL concurrency is not proven by the SQLite tests. The locking logic should be load-tested on PostgreSQL before production.
- Demo passwordless login is unsafe outside the local hackathon context.

## Verify on Windows

From `D:\AETHERX-Member4-SmartSlot\backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Our build: **25 passed** using isolated SQLite and simulated time. No Alembic migration is needed for this update (the existing `SlotOffer.kind` field stores `delay_shift`). Verify your actual PostgreSQL integration separately.

**Note about the frontend build:** React TSX syntax was checked. A complete Vite build could not be executed here because npm package tarballs were unavailable in the offline build environment. On your machine, in `frontend`, run `npm run build`; send any resulting errors and we'll fix them.

## What to explain to hackathon judges

"SmartSlot will never move another confirmed customer solely because someone is in traffic. It first checks a bounded rescheduling window, staff availability, booking conflicts and customer consent. A no-safe-slot decision is a valid safety outcome. Our demo ETA is simulated; integration with real traffic via Google Routes API is the next deployment phase."
