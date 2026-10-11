# AETHERX SmartSlot — TomTom live GPS (Mapbox comes later)

This is a focused update on the **AETHERX-Live-Google-GPS-Full** revision. It replaces Google-specific GPS routing and map display with TomTom Routing API and TomTom Raster Map Display API. **It does not alter Docker, PostgreSQL schema, appointment allocation, QR passes, or the simulation lab.**

## Install (Windows / VS Code)

1. **Back up your project** (`D:\AETHERX-Member4-SmartSlot`), particularly any files teammates edited.
2. Extract `AETHERX-TomTom-First-Update.zip` into your existing project folder, preserving `backend/` and `frontend/`. It deliberately excludes `.env` (your secrets), Docker volumes and `node_modules`.
3. Get two TomTom API keys at https://developer.tomtom.com/ under **My TomTom → API & SDK Keys**. It is possible to use the same key in development, but **two restricted keys** are more secure: one for the private server's Routing API, another for browser-exposed Map Display tiles.
4. In **`backend/.env`**, add this line (do not include quotation marks):

   ```dotenv
   TOMTOM_ROUTING_API_KEY=YOUR_SERVER_KEY
   ```

   Do not add this value to a Vite `VITE_...` variable. Make sure Routing API is authorized for this key.
5. In **`frontend/.env`**, add this line:

   ```dotenv
   VITE_TOMTOM_MAPS_KEY=YOUR_BROWSER_MAP_KEY
   ```

   In the TomTom dashboard, restrict the browser key to **Map Display** and allow only your development hosts (`localhost:5173`, `127.0.0.1:5173`) and later your deployed domain. This key is necessarily visible to browser visitors; set quotas/alerts in your TomTom account.
6. The old `GOOGLE_ROUTES_API_KEY` and `VITE_GOOGLE_MAPS_EMBED_KEY` may remain in your `.env`, but the updated GPS feature no longer uses them. Remove them later if not used elsewhere.
7. Set your real branch coordinates using **Admin → Settings**. The latitude/longitude must match the physical destination. This uses the current Business location fields, **no database migration needed**.
8. In VS Code PowerShell, run:

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot\backend
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
   ```

   In another terminal (restart Vite after editing `.env`):

   ```powershell
   cd D:\AETHERX-Member4-SmartSlot\frontend
   npm ci
   npm run build
   npm run dev
   ```

9. Choose **Customer** → **Travel & Arrival** (`http://localhost:5173/travel`). Have a confirmed booking within the next **48 hours** (the API intentionally restricts GPS to imminent appointments). Press **Start live GPS**, approve location permission, and wait for the route and ETA.

## What this does

- Browser Geolocation API supplies a permission-based device GPS fix, not fake coordinates.
- FastAPI requests `traffic=true`, `travelMode=car` from TomTom Calculate Route, and receives actual road distance, ETA, congestion delay when reported, and route coordinates.
- Customer receives a TomTom map with the actual route, destination marker, current position marker, zoom buttons, and updated travel time.
- Updated predictions can trigger **a single reception late-arrival alert** until the customer's status changes, while leaving their appointment intact.
- Location coordinates are not persisted in your PostgreSQL database. They are sent to TomTom to calculate a route, and map requests are sent to TomTom from the browser.
- Provider outage / invalid key returns an error: **no invented ETA fallback**.

## What is NOT included

- Automatic rescheduling across branches is **not** implemented yet.
- Mapbox integration is **not** in this update. We will implement it as the next optional provider after TomTom works on your laptop.
- Existing demo/Simulation Lab remains in the project; the live GPS feature itself no longer simulates traffic.
- App auth is still demo-grade; don't expose this app or your API keys publicly without proper identity protection.
- Browser GPS on Windows can be inaccurate or unavailable. For phone testing, use **HTTPS** rather than your laptop's plain `http://192.168...` address (geolocation requires a secure context).

## Verification performed here

- 40 Python backend tests passed with isolated SQLite (TomTom HTTP responses are mocked).
- TSX syntax/transpilation parsed successfully. Full `npm run build` could not be verified here because npm dependencies aren't available in the tool environment.
- Live TomTom requests **cannot be verified until you add an actual API key**. After that, verify one real trip from your location to your real branch.

## Troubleshooting

- **Missing TomTom key:** check `backend/.env` or `frontend/.env`; restart backend and Vite.
- **Map shows empty tiles:** check browser Network/Console; browser map key needs Map Display access and allowed origins. Inspect 401/403 and service limits.
- **No route/ETA:** ensure Routing API is allowed on the backend key, check a real booking within 48 hours, set destination coordinates, and inspect FastAPI logs (we never print your key).
- **GPS denied:** allow location in Chrome/Windows; on phones use HTTPS.
- **Tests pass, frontend build fails:** paste the first TypeScript compiler error; don't delete existing app pages or dependencies.

Official docs:
- https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route
- https://docs.tomtom.com/map-display-api/documentation/tomtom-maps/v1/raster/map-tile
- https://docs.tomtom.com/platform/documentation/api-best-practices/api-key-management-best-practices
