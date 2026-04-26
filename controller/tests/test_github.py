import hashlib
import hmac

from controller import github


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def test_verify_signature_valid():
    body = b'{"foo":"bar"}'
    sig = _sign("topsecret", body)
    assert github.verify_signature(secret="topsecret", body=body, header=sig) is True


def test_verify_signature_wrong_secret():
    body = b'{"foo":"bar"}'
    sig = _sign("other", body)
    assert github.verify_signature(secret="topsecret", body=body, header=sig) is False


def test_verify_signature_missing_header():
    assert (
        github.verify_signature(secret="topsecret", body=b"{}", header=None) is False
    )


def test_verify_signature_malformed_header():
    assert (
        github.verify_signature(secret="topsecret", body=b"{}", header="garbage")
        is False
    )
