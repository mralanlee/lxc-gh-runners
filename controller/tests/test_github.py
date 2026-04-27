import hashlib
import hmac

import httpx
import pytest
import respx

from controller import github
from controller.github import GitHubClient


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
    assert github.verify_signature(secret="topsecret", body=b"{}", header=None) is False


def test_verify_signature_malformed_header():
    assert github.verify_signature(secret="topsecret", body=b"{}", header="garbage") is False


@pytest.fixture
def client():
    return GitHubClient(pat="ghp_test", org="myorg")


@respx.mock
async def test_generate_jit_config(client):
    route = respx.post("https://api.github.com/orgs/myorg/actions/runners/generate-jitconfig").mock(
        return_value=httpx.Response(201, json={"encoded_jit_config": "JITSTRING"})
    )
    jit = await client.generate_jit_config(name="runner-42", labels=["self-hosted", "lxc"])
    assert jit == "JITSTRING"
    assert route.called
    sent = route.calls.last.request
    assert b"runner-42" in sent.content
    assert b"self-hosted" in sent.content


@respx.mock
async def test_get_workflow_job(client):
    respx.get("https://api.github.com/repos/myorg/anyrepo/actions/jobs/42").mock(
        return_value=httpx.Response(
            200, json={"id": 42, "status": "completed", "conclusion": "success"}
        )
    )
    job = await client.get_workflow_job(repo="myorg/anyrepo", job_id=42)
    assert job["status"] == "completed"


@respx.mock
async def test_generate_jit_config_http_error(client):
    respx.post("https://api.github.com/orgs/myorg/actions/runners/generate-jitconfig").mock(
        return_value=httpx.Response(422, json={"message": "bad labels"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_jit_config(name="runner-1", labels=["x"])
