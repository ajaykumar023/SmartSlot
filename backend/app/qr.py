import hashlib, io, secrets, base64
import qrcode


def create_pass() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    image = qrcode.make(token)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return token, "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
