import hashlib
import hmac


def verify_signature(*, secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header[len("sha256="):]
    return hmac.compare_digest(expected, received)
