# SmartSlot architecture

SmartSlot is a multi-business demo with four seeded profiles (salon, clinic, repair center, and consultant). Business-owned rows and operations are scoped by `business_id`. The browser selection is context only; signed token claims enforce customer and admin access. It uses a React + TypeScript + Vite browser app, FastAPI + Pydantic API, SQLAlchemy 2.x, Alembic, and PostgreSQL.

```text
Browser (React Router)
  └── shared api.ts ── Bearer demo session ── FastAPI routes
                                              ├── auth.py: HMAC session checks
                                              ├── scheduling.py: deterministic availability
                                              ├── qr.py: opaque random QR token + SHA-256 storage
                                              ├── waitlist.py: matching and simulated in-app notice
                                              └── SQLAlchemy ── PostgreSQL
```

Booking checks availability twice inside the transaction and locks the selected staff row before the second check. Availability intersects active business hours, active staff shifts, service qualifications, service duration, buffers, and existing bookings in the business timezone. This serializes concurrent booking attempts for that staff member. PostgreSQL constraints protect references and unique token hashes; a database exclusion constraint is not currently configured.

## State behavior

`confirmed → checked_in` is performed by the admin scanner/manual reference endpoint. `confirmed → cancelled` is allowed by the customer up to two hours before start. Queue-shift requests set `at_risk` for visibility while preserving original time; acceptance moves the same booking to the offered time, and decline restores `confirmed`. Waitlist offers require acceptance before a new appointment is created. Duplicate check-in and invalid/expired states return conflicts.

## API examples

- `GET /api/health` and `GET /api/ready`
- `POST /api/auth/demo` with `{ "role":"customer", "name":"Alex Morgan", "email":"alex@example.com", "business_id":1 }`
- `GET /api/businesses`, `GET /api/services?business_id=1`
- `GET /api/slots?business_id=1&service_id=1&date_from=2026-10-12&date_to=2026-10-12`
- `POST /api/appointments` with service, ISO datetime, customer name/email; requires the customer bearer token
- `GET /api/appointments/mine`, `POST /api/appointments/{reference}/cancel`
- Admin: `/api/admin/dashboard`, `/api/admin/appointments`, `/api/admin/check-in?code=SS-ABC123`
- Offers: `/api/offers`, `POST /api/offers/{id}/accept` or `/decline`

FastAPI's generated OpenAPI UI is available at `http://localhost:8000/docs` while the API is running.
