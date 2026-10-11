# AETHERX SmartSlot — Secure Demo Login Update

A **focused patch** for the current FastAPI backend with Alembic revision `0009_auth_conflicts_delivery` and the React/Vite frontend. Not a complete application. No Alembic migration required.

## What changes

- Replaces `/api/auth/demo` frontend calls with **POST `/api/auth/login`**. Passwords are checked by FastAPI against salted, hashed PostgreSQL account credentials.
- Shows email + password (with optional visibility toggle) instead of *Alex Morgan* and a name-only login.
- Adds a login entry and simple authenticated employee workspace using **GET `/api/employee/my-appointments`** and **PUT `/api/employee/my-presence`**.
- Allows sign-in as **Customer**, **Employee**, or **Reception/Admin**, using the existing per-branch backend role permissions.
- Adds a **fictional-customer-only** seeder that creates customer accounts from already existing AETHERX showcase bookings. Existing accounts/passwords are untouched. **No admin or employee passwords are pre-seeded.**

## Prerequisites

- Phase 4 plus backend hardening patch installed, revision `0009_auth_conflicts_delivery` already applied.
- Demo showcase bookings are present. New customer accounts are created **only** for existing fictional `@aetherx.example` booking emails at the `showcase_*` demo businesses.
- Your existing backend `.env` has a unique `APP_SECRET` of at least 32 characters.
- Local-only fictional demo. **Do not use shared demo passwords or seeded fake accounts on any public deployment.**

## Install in Windows PowerShell

1. Stop FastAPI and Vite. Make a database backup from your project root:

```powershell
cd D:\AETHERX-Member4-SmartSlot
docker compose exec db pg_dump -U smartslot -d smartslot -Fc -f /tmp/before-login.patch.dump
if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
docker compose cp db:/tmp/before-login.patch.dump .\before-login.patch.dump
if ($LASTEXITCODE -ne 0) { throw 'Copying backup failed' }
```

2. Download `AETHERX-Secure-Demo-Login-Patch.zip` into `Downloads`. Preserve backups of these frontend files before extracting:

```powershell
Copy-Item .\frontend\src\App.tsx .\frontend\src\App.before-secure-login.tsx.bak
Copy-Item .\frontend\src\types.ts .\frontend\src\types.before-secure-login.ts.bak
Copy-Item .\frontend\src\pages\Welcome.tsx .\frontend\src\pages\Welcome.before-secure-login.tsx.bak
Expand-Archive "$env:USERPROFILE\Downloads\AETHERX-Secure-Demo-Login-Patch.zip" -DestinationPath . -Force
```

3. In `backend/.env`, ensure the old insecure demo options are disabled:

```dotenv
ALLOW_INSECURE_DEMO_LOGIN=false
ALLOW_INSECURE_DEMO_ADMIN=false
```

Leave your other working `.env` settings in place. Don't expose your APP_SECRET or TomTom keys.

4. Preview which fictional accounts will be created:

```powershell
cd .\backend
.\.venv\Scripts\python.exe seed_demo_logins.py
```

5. Only if the preview lists the expected fictional customers, **apply**:

```powershell
$env:AETHERX_DEMO_WRITE='YES'
try {
    .\.venv\Scripts\python.exe seed_demo_logins.py --apply
    if ($LASTEXITCODE -ne 0) { throw 'Login seed failed' }
}
finally {
    Remove-Item Env:AETHERX_DEMO_WRITE -ErrorAction SilentlyContinue
}
```

At the **hidden password prompts**, enter `Welcome1234!` twice for **new fictional customer accounts only**. (The example `Welcome1234` is 11 characters; the current FastAPI code requires at least 12.) No password is printed or saved in the manifest. Repeating the seed is safe and skips already existing accounts.

6. Test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1
```

In a **separate** terminal:

```powershell
cd D:\AETHERX-Member4-SmartSlot\frontend
npm install
npm run build
npm run dev
```

7. At `http://localhost:5173`, choose the exact branch reported by the preview, then **Continue as customer**. Example: `demo.asha@aetherx.example`, password `Welcome1234!`, **AETHERX Showcase Studio A**. Login requires the selected business to be one that the fictional account has been granted. The success response contains a signed bearer token and user name; the frontend stores it and navigates to the customer pages.

For employee and admin accounts, use your already-installed management CLI (password is entered at a hidden prompt):

```powershell
cd D:\AETHERX-Member4-SmartSlot\backend
.\.venv\Scripts\python.exe manage_accounts.py create --email admin@example.com --name "Demo Admin" --business-id 1 --role admin
# Employee additionally requires --staff-id <ID of a staff member at that business>:
.\.venv\Scripts\python.exe manage_accounts.py create --email employee@example.com --name "Demo Employee" --business-id 1 --role employee --staff-id 1
```

**IDs above are examples**. Select valid business and staff IDs from your database. Admin/employee passwords should be different from customer demo passwords.

## Troubleshooting

- `401`: invalid email or password; existing accounts were deliberately not reset.
- `403`: account exists but lacks **the selected business and role**, or demo login endpoint was invoked accidentally.
- `503`: `APP_SECRET` is still missing/too short/placeholder.
- No accounts previewed: `demo_showcase_seed.py --apply` and `demo_finalize_seed.py --apply` have not been applied, or the selected existing bookings aren't in `showcase_*` demo branches.
- Old page persists: hard-refresh Vite, restart the frontend, sign out, and clear previous `smartslot_token` / `smartslot_user` from browser localStorage if required.
- TypeScript build errors: run `npm install` in `frontend` before `npm run build`.

## Validated in the isolated environment

- Python secure account seed and API login tests: **2 passed**.
- Entire previously integrated backend suite plus new tests: **101 passed, 2 skipped** (SQLite setup, not your Docker PostgreSQL).
- React `.tsx` and `.ts` code passes **TypeScript syntax parsing**. A full Vite build could not be completed in this environment because npm dependencies were not fully available; the build must be run on your laptop.

## Security limitations

- Shared `Welcome1234!` is exclusively for fictional offline/local demo customers. Use unique credentials for anything exposed online.
- Existing frontend caches a bearer token in `localStorage`, which is convenient for a hackathon but not the recommended production session design. Use hardened HTTP-only cookies, CSRF/XSS protection, rate limiting, and verified account onboarding for real users.
- Backend `manage_accounts.py` does not sign up customers publicly or send email verification. Fake `.example` emails cannot receive mail.
