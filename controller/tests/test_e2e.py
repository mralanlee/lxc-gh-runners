import asyncio
import hashlib
import hmac
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from controller import db, webhook, worker


def _sign(secret: str, body: bytes) -> str:
    return f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


async def test_full_lifecycle():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)

    proxmox = MagicMock()
    proxmox.allocate_vmid.return_value = 9100
    github_client = MagicMock()
    github_client.generate_jit_config = AsyncMock(return_value="JITSTRING")

    app = FastAPI()
    app.include_router(
        webhook.build_router(
            conn=conn, secret="s", runner_labels=["self-hosted", "lxc"]
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        body = json.dumps({
            "action": "queued",
            "workflow_job": {"id": 100, "labels": ["self-hosted", "lxc"]},
            "repository": {"full_name": "myorg/repo"},
        }).encode()
        r = await client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign("s", body), "X-GitHub-Event": "workflow_job"},
        )
        assert r.status_code == 200

        await worker.spawn_pass(
            conn=conn, proxmox=proxmox, github=github_client,
            cap=3, template_vmid=9000, vmid_range=(9100, 9199),
            runner_labels=["self-hosted", "lxc"],
        )

        row = conn.execute("SELECT * FROM runners WHERE job_id=100").fetchone()
        assert row["state"] == "running"
        assert row["vmid"] == 9100

        body2 = json.dumps({
            "action": "completed",
            "workflow_job": {"id": 100, "labels": ["self-hosted", "lxc"]},
            "repository": {"full_name": "myorg/repo"},
        }).encode()
        r = await client.post(
            "/webhook/github",
            content=body2,
            headers={"X-Hub-Signature-256": _sign("s", body2), "X-GitHub-Event": "workflow_job"},
        )
        assert r.status_code == 200

        await worker.cleanup_pass(conn=conn, proxmox=proxmox)

        row = conn.execute("SELECT * FROM runners WHERE job_id=100").fetchone()
        assert row["state"] == "cleaned"
        proxmox.stop.assert_called_with(vmid=9100)
        proxmox.destroy.assert_called_with(vmid=9100)
