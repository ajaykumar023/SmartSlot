from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import issue_token
from app.database import Base, get_db
from app.main import app
from app.models import Appointment, Business, Service, Staff
from app.qr import token_hash


@pytest.fixture
def check_in_setup():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        business = Business(name="Check In Studio", category="salon", timezone="UTC", active=True,
            is_demo=True, check_in_minutes=30)
        db.add(business)
        db.flush()
        service = Service(business_id=business.id, name="Consultation", description="", duration_minutes=30, active=True)
        staff = Staff(business_id=business.id, name="Alex", title="Specialist", active=True)
        db.add_all([service, staff])
        db.flush()
        qr_secret = "opaque-check-in-secret"
        appointment = Appointment(business_id=business.id, service_id=service.id, staff_id=staff.id,
            customer_email="taylor@example.com", customer_name="Taylor Customer", reference="SS-CHECK1",
            qr_token_hash=token_hash(qr_secret), starts_at=now + timedelta(minutes=5),
            ends_at=now + timedelta(minutes=35), duration_minutes=30, buffer_minutes=0, status="confirmed")
        db.add(appointment)
        db.commit()
        business_id, appointment_id = business.id, appointment.id

    def override_get_db():
        with Session(engine) as db:
            yield db

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client, engine, business_id, appointment_id, qr_secret
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    engine.dispose()


def customer_headers(business_id: int, email: str = "taylor@example.com"):
    return {"Authorization": f"Bearer {issue_token('customer', 'Taylor Customer', email, business_id)}"}


def test_customer_self_check_in_valid_qr_reuses_appointment(check_in_setup):
    client, engine, business_id, appointment_id, qr_secret = check_in_setup

    response = client.post("/api/appointments/self-check-in", json={"token": qr_secret}, headers=customer_headers(business_id))

    assert response.status_code == 200, response.text
    assert response.json()["id"] == appointment_id
    assert response.json()["status"] == "checked_in"
    assert response.json()["customer_name"] == "Taylor Customer"
    with Session(engine) as db:
        assert len(db.scalars(select(Appointment)).all()) == 1
        assert db.get(Appointment, appointment_id).status == "checked_in"


def test_customer_self_check_in_rejects_invalid_qr(check_in_setup):
    client, _, business_id, _, _ = check_in_setup

    response = client.post("/api/appointments/self-check-in", json={"token": "not-a-valid-pass"}, headers=customer_headers(business_id))

    assert response.status_code == 404
    assert response.json()["detail"] == "QR pass not found for this customer"


def test_customer_self_check_in_requires_auth_and_appointment_ownership(check_in_setup):
    client, engine, business_id, appointment_id, qr_secret = check_in_setup

    no_auth = client.post("/api/appointments/self-check-in", json={"token": qr_secret})
    other_customer = client.post("/api/appointments/self-check-in", json={"token": qr_secret},
        headers=customer_headers(business_id, "other@example.com"))
    admin_token = issue_token("admin", "Admin", "admin@smartslot.demo", business_id, [business_id])
    admin = client.post("/api/appointments/self-check-in", json={"token": qr_secret},
        headers={"Authorization": f"Bearer {admin_token}"})

    assert no_auth.status_code == 401
    assert other_customer.status_code == 404
    assert admin.status_code == 403
    with Session(engine) as db:
        assert db.get(Appointment, appointment_id).status == "confirmed"


def test_customer_self_check_in_rejects_appointment_outside_window(check_in_setup):
    client, engine, business_id, appointment_id, qr_secret = check_in_setup
    with Session(engine) as db:
        row = db.get(Appointment, appointment_id)
        row.starts_at = datetime.now(timezone.utc) + timedelta(minutes=90)
        row.ends_at = row.starts_at + timedelta(minutes=30)
        db.commit()

    response = client.post("/api/appointments/self-check-in", json={"token": qr_secret}, headers=customer_headers(business_id))

    assert response.status_code == 409
    assert "Check-in opens" in response.json()["detail"]
    with Session(engine) as db:
        assert db.get(Appointment, appointment_id).status == "confirmed"


def test_customer_repeated_self_scans_return_clear_conflict(check_in_setup):
    client, engine, business_id, appointment_id, qr_secret = check_in_setup
    headers = customer_headers(business_id)

    first = client.post("/api/appointments/self-check-in", json={"token": qr_secret}, headers=headers)
    second = client.post("/api/appointments/self-check-in", json={"token": qr_secret}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Appointment is already checked in"
    with Session(engine) as db:
        assert len(db.scalars(select(Appointment)).all()) == 1
        assert db.get(Appointment, appointment_id).status == "checked_in"


def test_reception_check_in_still_accepts_qr_token(check_in_setup):
    client, engine, business_id, appointment_id, qr_secret = check_in_setup
    admin_token = issue_token("admin", "Admin", "admin@smartslot.demo", business_id, [business_id])

    response = client.post(f"/api/admin/check-in?business_id={business_id}&code={qr_secret}",
        headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200, response.text
    assert response.json()["id"] == appointment_id
    assert response.json()["status"] == "checked_in"
    with Session(engine) as db:
        assert len(db.scalars(select(Appointment)).all()) == 1
        assert db.get(Appointment, appointment_id).status == "checked_in"
