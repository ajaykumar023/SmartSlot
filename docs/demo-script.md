# SmartSlot demo walkthrough

1. Start PostgreSQL, apply Alembic migrations, seed the four demo businesses, and start API + frontend as listed in the root README.
2. Open `http://localhost:5173`, choose a business (salon, clinic, repair center, or consulting practice), and enter the customer demo with `Alex Morgan` and `alex@example.com`.
3. Choose **Book a service**, select a service and date, then request available times. Select a result and confirm with the same demo email. Show the reference and QR pass.
4. Open **My bookings** and **Queue & offers** to review persisted status and any offers. Join the waitlist from the booking form when an opening is unavailable.
5. Switch role to admin and enter `admin@smartslot.demo`. Show appointment records and the check-in desk. For an appointment starting within 30 minutes, scan its QR or enter its booking reference. The API rejects early or duplicate check-in.
6. In **Smart Queue Shift**, offer an earlier time to an eligible confirmed booking. Switch back to that customer and explicitly accept or decline. The original booking stays reserved until acceptance; no automatic cancellation occurs.
7. In-app notifications are simulated and clearly labelled. The Best-Fit panel ranks feasible slots deterministically; there is no trained AI or external delay feed.

Demo records are fictional. Each business has its own services, staff qualifications, hours, timezone, and queue policies. All four current profiles use Asia/Kolkata with different operating schedules.
