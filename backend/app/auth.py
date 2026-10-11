import base64, hashlib, hmac, json, time
from fastapi import HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .config import settings

bearer = HTTPBearer(auto_error=False)


def issue_token(role: str, name: str, email: str, business_id: int, business_ids: list[int] | None = None) -> str:
    payload = json.dumps({"role": role, "name": name, "email": email.lower(), "business_id": business_id,
        "business_ids": business_ids or [business_id], "exp": int(time.time()) + 86400 * 30}, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, "Sign in to continue")
    try:
        body, signature = credentials.credentials.split(".", 1)
        expected = hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        user = json.loads(raw)
        if user["exp"] < time.time():
            raise ValueError("expired")
        return user
    except Exception as exc:
        raise HTTPException(401, "Session expired. Please sign in again.") from exc


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user
