# AETHERX SmartSlot — Real Google Maps + Google Routes GPS

This update **replaces the GPS screen's OpenStreetMap view and straight-line simulated estimates** with a Google Maps route and Google Routes traffic-aware road distance / duration. It does **not** implement automatic cross-branch transfer. Existing appointments remain confirmed even when the ETA is late.

## What's included

- Customer `/travel`: Start live GPS, Stop tracking, Refresh traffic ETA, Google Maps directions route, and late/on-time predictions. Location permission is required.
- Backend `/api/travel/provider-status`: tells the app whether the Google Routes server-side key is configured. **Never returns the key.**
- Backend `/api/appointments/{reference}/travel-eta`: uses Google's traffic-aware Routes API. If no key is present or Google is unavailable, returns an error **instead of made-up kilometers or minutes**.
- Retains your PostgreSQL business latitude/longitude and `customer_arrivals` status/ETA. Does not save exact customer GPS coordinates.

## 1. Install the patch

1. Back up your project, especially any teammate edits.
2. Extract `AETHERX-Live-Google-GPS-Update.zip` into `D:\AETHERX-Member4-SmartSlot` preserving `backend/` and `frontend/` folders.
3. Do not replace your existing `.env` files with `.env.example`.
4. No database migration is required if you previously applied migration `0004_geosmart_automation.py`.

## 2. Enable Google APIs and create TWO separate keys

Go to <https://console.cloud.google.com/>. Choose/create a Google Cloud project and enable billing. Enable **Routes API** and **Maps Embed API**.

**Private backend key:** Create a key, restrict its API access to **Routes API**, and put it in `backend/.env`:

```
GOOGLE_ROUTES_API_KEY=your_routes_server_key
```

This key is only used server-side in FastAPI. Never put it in `frontend/.env` or source control. Apply an appropriate server-side application restriction when you have a stable outbound IP; for local development, API restrictions and low quotas are particularly important.

**Browser map key:** Create a SECOND key, restrict its API access to **Maps Embed API**, and restrict websites (HTTP referrers) to your local dev addresses, such as `http://localhost:5173/*` and `http://127.0.0.1:5173/*`. Add this to `frontend/.env` (create it if missing):

```
VITE_GOOGLE_MAPS_EMBED_KEY=your_embed_browser_key
```

The browser key is visible in the frontend **by design**. The website and API restrictions protect it. **Do not reuse your Routes server key as the frontend browser key.**

Official documentation:
- <https://developers.google.com/maps/documentation/routes>
- <https://developers.google.com/maps/documentation/embed/get-api-key>
- <https://developers.google.com/maps/documentation/embed/embedding-map>
- <https://developers.google.com/maps/billing-and-pricing/pricing>

Google Maps Embed is no-charge for usage, but billing and a key are still required. Routes API can incur charges; set quotas and billing alerts. Never post your API keys in a screenshot or chat.

## 3. Configure a real business destination

Sign in as an admin for the selected business. Go to **Admin > Settings**. Enter the physical branch latitude/longitude and save. Do not use arbitrary demonstration coordinates for real ETAs.

## 4. Start servers

**Backend terminal:**

```powershell
cd D:\AETHERX-Member4-SmartSlot\backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

**Frontend terminal:**

```powershell
cd D:\AETHERX-Member4-SmartSlot\frontend
npm run build
npm run dev
```

Restart Vite after changing `frontend/.env`. Restart Uvicorn after changing `backend/.env` (environment changes may not trigger auto-reload).

## 5. Test REAL GPS

1. Log in as a customer for the same business and ensure you have a confirmed appointment **within the next 48 hours**, still active. The server intentionally refuses GPS ETA for far-future bookings.
2. Open <http://localhost:5173/travel> and choose the appointment.
3. Click **Start live GPS** and grant Chrome location permission.
4. The map should show the road route, while Google Routes provides **road distance, traffic-aware drive minutes, and arrival prediction**.
5. Click **Refresh traffic ETA**, **Open Google Maps navigation**, and **Stop tracking**.

**Troubleshooting:**
- `Google Routes API is not configured` → backend key missing or server not restarted.
- Map says API key restriction error → check Maps Embed is enabled, billing attached, browser key and website restrictions.
- `Location ... only available shortly before ...` → create a real near-time appointment; do not change your system clock.
- GPS doesn't appear on another device at `http://192.168...:5173` → geolocation usually requires HTTPS outside localhost.
- Route API 403/429 → check allowed APIs, quotas, billing, server key and network.
- GPS inaccurate → try a phone outdoors or another device with actual GPS hardware. Desktop may use Wi-Fi location.

## 6. What the database already stores

`businesses.latitude` and `businesses.longitude`: business location.
`customer_arrivals`: appointment_id, status, ETA minutes, update time.
`admin_alerts`: traffic risk alert when Google predicts likely late.

**Exact customer coordinates are NOT stored.** The coordinates are transmitted to Google to compute and display a route. No database migration is necessary for this GPS milestone.

## Next backend/database milestone

Once the live Google ETA works, add `organizations` / `branches` relationships, `service_compatibility` and `staff_skills`, explicit `auto_reroute_opt_in` for each appointment, and an audited, transactional appointment transfer. Enforce no double-booking with PostgreSQL constraints and row locks, and never silently move appointments to unrelated businesses.

## Verification performed here

- Backend: **38 tests passed** (test database SQLite, including mocked Routes response and no-key rejection).
- Frontend: changed TSX passed TypeScript syntax transpilation.
- A full Vite build could not be run here because npm dependencies were unavailable in this environment; run `npm run build` on your Windows machine.
- Live Google response and billing were **not tested**; you must add your keys and try a real route locally.
