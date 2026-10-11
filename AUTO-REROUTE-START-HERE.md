# AETHERX GeoSmart — Automatic Cross-Branch Reroute (SIMULATION)

## New behavior

In the **Admin → Simulation Lab**, the customer now **does not need to tap Accept** for each suggested reroute. They previously enabled **Auto-reroute authorized at booking** (toggle inside this fictional admin demo). With that permission, the demo:

1. Sees an **illustrative** traffic ETA for Rahul's original Northstar Central booking at 10:00.
2. If he can reach Central by its configured grace deadline, leaves the appointment unchanged.
3. Otherwise checks **Northstar Central, Northstar East and Northstar South**. These are **fictional branches** of the **same fictional clinic organization**, not independent businesses.
4. Excludes slots if a qualified clinician/service is missing, the slot is occupied, the arrival is too late (5-minute buffer), or the start exceeds the 15/30-minute postponement cap.
5. Ranks eligible slots by **earliest appointment completion**, breaking ties by **driving time**. This is more useful than choosing the physically closest clinic with a much later slot.
6. Instantly reassigns Rahul **in the simulation only**, without a second approval screen. No other patient's confirmed appointment changes. The original appointment is **simulated as released**, with Meera getting only a temporary waitlist offer.
7. If opt-in is off or no suitable alternative exists, retains the original appointment and flags staff/customer review.

**No database writes are made by this simulator.** Real-time GPS, Google Maps traffic, production cross-business transfers and real QR reissuance are **NOT yet implemented**. This feature demonstrates the product logic, not an active rerouting service.

## Install update on Windows

Extract **AETHERX-GeoSmart-AutoReroute-Update.zip** into:

`D:\AETHERX-Member4-SmartSlot`

Preserve the `backend/` and `frontend/` directories and overwrite those **specific update files** after backing up anything teammates edited. No new Python packages or database migration are needed for the simulator.

Keep Docker/PostgreSQL running, restart or use the existing FastAPI auto-reload process:

```powershell
cd D:\AETHERX-Member4-SmartSlot\backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```powershell
cd D:\AETHERX-Member4-SmartSlot\frontend
npm run dev
```

Visit `http://localhost:5173/admin/simulation`, logged in as a clinic demo **admin**.

### Scenarios

| Scenario | Expected result with auto-reroute toggle ON, +25 min traffic |
|---|---|
| Traffic jam + reachable clinic | Rahul automatically moves from Northstar Central 10:00 to **Northstar East 10:00**; traffic ETA East is 14 min |
| Nearest branch is full | Automatically route to **Northstar South 10:15** |
| Nearest doctor not qualified | Reject East, route to **Northstar South 10:15** |
| All safe slots booked | **No transfer**; staff review |
| Customer on time (+3 min traffic) | **Keep Northstar Central 10:00** |
| Auto-reroute toggle OFF | **No transfer**, even if a closer slot exists |

## New backend demo API

`POST /api/admin/simulation/geo-reroute?business_id=2` with demo **admin** JWT:

```json
{
  "scenario": "gap",
  "traffic_delay_minutes": 25,
  "max_delay_minutes": 30,
  "auto_reroute_opt_in": true
}
```

Returns `selected`, `branches_checked`, `customers`, `events`, `outcome`, and `simulation_only: true`.

Previous `/api/admin/simulation/limited-delay` endpoint remains for backwards compatibility and old tests. The frontend now uses `/api/admin/simulation/geo-reroute`.

## To build the real version next

- Add **organization / branch membership** and lat/long in PostgreSQL, including an admin-only API for known physical branch locations.
- Add a **customer booking-time auto-reroute preference** and rules for allowed branches, services, urgency and max change. The setting should never default ON in real accounts.
- With browser GPS permission, send a timestamped location once / at limited intervals, rather than silently monitoring continuously. Get traffic-aware *driving time* with Google Routes API or a compatible provider; never rely on straight-line distance for feasibility.
- Fetch live matching slots for all participating branches and verify **same service, clinician qualifications, remaining lead time**, cancellation/payment rules and actual slot holds.
- **Atomically** reserve the new booking and release the old one with database locking, preventing two customers from acquiring the same slot; reissue QR bound to the destination business, write an audit entry and notify customer immediately.
- Do not auto-transfer urgent/specialist visits unless the organization explicitly supports equivalent providers. If live ETA becomes unreliable, no safe alternative exists, or location permission is denied, **retain the booking** and escalate instead.

These production tasks are still pending. The simulator must not be presented to judges as real Google traffic integration.
