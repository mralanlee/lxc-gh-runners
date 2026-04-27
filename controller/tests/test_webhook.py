import hashlib
import hmac
import json
import sqlite3

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from controller import db
from controller.webhook import build_router


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


@pytest.fixture
def app_and_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)

    app = FastAPI()
    app.include_router(
        build_router(conn=conn, secret="test-secret", runner_labels=["self-hosted", "lxc"])
    )
    return app, conn


@pytest.fixture
async def client(app_and_conn):
    app, _ = app_and_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _post(client, body: dict, *, action: str, event: str = "workflow_job"):
    raw = json.dumps(body).encode()
    return await client.post(
        "/webhook/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": _sign("test-secret", raw),
            "X-GitHub-Event": event,
        },
    )


async def test_invalid_signature_returns_401(client):
    r = await client.post(
        "/webhook/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "workflow_job"},
    )
    assert r.status_code == 401


async def test_unknown_event_type_returns_200(client):
    r = await _post(client, {}, action="anything", event="push")
    assert r.status_code == 200


async def test_queued_inserts_pending_row(app_and_conn, client):
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 12345, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    row = conn.execute("SELECT * FROM runners WHERE job_id=12345").fetchone()
    assert row["state"] == "pending"
    assert row["repo"] == "myorg/repo"


async def test_duplicate_queued_is_ignored(app_and_conn, client):
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 1, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, body, action="queued")
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    rows = conn.execute("SELECT * FROM runners WHERE job_id=1").fetchall()
    assert len(rows) == 1


async def test_in_progress_updates_state(app_and_conn, client):
    _, conn = app_and_conn
    queued = {
        "action": "queued",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, queued, action="queued")
    in_prog = {
        "action": "in_progress",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, in_prog, action="in_progress")
    row = conn.execute("SELECT * FROM runners WHERE job_id=7").fetchone()
    assert row["state"] == "running"


async def test_completed_updates_state(app_and_conn, client):
    _, conn = app_and_conn
    queued = {
        "action": "queued",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, queued, action="queued")
    done = {
        "action": "completed",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, done, action="completed")
    row = conn.execute("SELECT * FROM runners WHERE job_id=7").fetchone()
    assert row["state"] == "completed"


async def test_self_hosted_only_job_is_ignored(app_and_conn, client):
    """A bare self-hosted job is not ours — could belong to another runner pool."""
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 201, "labels": ["self-hosted"]},
        "repository": {"full_name": "myorg/repo"},
    }
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    assert conn.execute("SELECT * FROM runners WHERE job_id=201").fetchone() is None


async def test_job_with_extra_labels_is_processed(app_and_conn, client):
    """Job opts in to our fleet by including all RUNNER_LABELS; extra labels OK."""
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 200, "labels": ["self-hosted", "lxc", "gpu"]},
        "repository": {"full_name": "myorg/repo"},
    }
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    row = conn.execute("SELECT * FROM runners WHERE job_id=200").fetchone()
    assert row is not None


async def test_completed_then_in_progress_does_not_regress(app_and_conn, client):
    _, conn = app_and_conn
    queued = {
        "action": "queued",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, queued, action="queued")
    # Manually mark cleaned (worker would do this normally).
    conn.execute("UPDATE runners SET state='cleaned' WHERE job_id=7")
    # Out-of-order in_progress arrives after the job is already cleaned up.
    in_prog = {
        "action": "in_progress",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
        "repository": {"full_name": "myorg/repo"},
    }
    await _post(client, in_prog, action="in_progress")
    row = conn.execute("SELECT state FROM runners WHERE job_id=7").fetchone()
    assert row["state"] == "cleaned"
