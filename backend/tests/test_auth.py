from app.auth import current_user, issue_token
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from app.main import app
from app.qr import create_pass, token_hash


def test_demo_session_round_trip():
    token = issue_token("customer", "Alex Morgan", "alex@example.com", 7)
    user = current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    assert user["email"] == "alex@example.com"
    assert user["role"] == "customer"
    assert user["business_id"] == 7


def test_tampered_session_is_rejected():
    token = issue_token("admin", "Admin", "admin@smartslot.demo", 1, [1, 2, 3, 4]) + "tampered"
    try:
        current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    except HTTPException as error:
        assert error.status_code == 401
    else:
        raise AssertionError("tampered session was accepted")


def test_public_health_and_server_side_admin_guard():
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/admin/appointments").status_code == 401


def test_qr_pass_is_opaque_and_hashed():
    token, image = create_pass()
    assert len(token_hash(token)) == 64
    assert token_hash(token) != token
    assert image.startswith("data:image/png;base64,")
