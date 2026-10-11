# SmartSlot Customer Work Copy

This is a full, independent source copy of SmartSlot for parallel development.

## Your ownership

**Primary file:** `frontend/src/pages/Customer.tsx`

**Scope:** Customer booking, services, available slots, booking confirmation/QR, customer bookings, waitlist/queue offers, notifications.

Create role-specific components under `frontend/src/components/customer/` and optional styles in `frontend/src/customer.css` rather than editing the other developer's files.

## Please leave shared files alone unless both developers agree

- `frontend/src/App.tsx`
- `frontend/src/routes.ts`
- `frontend/src/api.ts`
- `frontend/src/types.ts`
- `frontend/src/styles.css`
- `frontend/package.json` and `frontend/package-lock.json`
- Everything in `backend/` (routes, schemas, models, migrations, seed data)

Do not edit Admin.tsx or shared integration files without agreement.

## Development setup

1. Read `README.md` for the project setup.
2. Copy `backend/.env.example` to `backend/.env` and configure your local PostgreSQL connection and a unique `APP_SECRET`. Do not share `.env` files or passwords.
3. In `backend/`, activate your Python virtual environment, install `requirements.txt`, run `alembic upgrade head`, then `python seed.py`.
4. Run the backend with `uvicorn app.main:app --reload --port 8000`.
5. In another terminal, run `npm install` and `npm run dev` from `frontend/`.

## When handing back your work

Return this full project ZIP plus a short list of changed files. Do not include `.venv`, `node_modules`, `dist`, or `.env`. Do not claim an endpoint works unless it was tested against the real API.
