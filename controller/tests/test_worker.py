import sqlite3
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from controller import db
from controller.worker import spawn_pass, cleanup_pass


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    db.init_schema(c)
    yield c
    c.close()


@pytest.fixture
def proxmox():
    p = MagicMock()
    p.allocate_vmid.return_value = 9100
    return p


@pytest.fixture
def github_client():
    g = MagicMock()
    g.generate_jit_config = AsyncMock(return_value="JITSTRING")
    return g


async def test_spawn_pass_does_nothing_when_at_cap(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=1)
    db.update_state_by_job_id(conn, job_id=1, new_state="spawning")
    db.insert_pending_runner(conn, job_id=2)

    await spawn_pass(
        conn=conn, proxmox=proxmox, github=github_client,
        cap=1, template_vmid=9000, vmid_range=(9100, 9199),
        runner_labels=["self-hosted", "lxc"],
    )
    proxmox.clone.assert_not_called()


async def test_spawn_pass_happy_path(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=42)

    await spawn_pass(
        conn=conn, proxmox=proxmox, github=github_client,
        cap=3, template_vmid=9000, vmid_range=(9100, 9199),
        runner_labels=["self-hosted", "lxc"],
    )

    proxmox.clone.assert_called_once_with(template_vmid=9000, new_vmid=9100)
    proxmox.set_description.assert_called_once()
    proxmox.start.assert_called_once_with(vmid=9100)
    proxmox.wait_until_ready.assert_called_once_with(vmid=9100)
    assert proxmox.exec.call_count == 2

    row = conn.execute("SELECT * FROM runners WHERE job_id=42").fetchone()
    assert row["state"] == "running"
    assert row["vmid"] == 9100


async def test_spawn_pass_marks_failed_on_exception(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=42)
    proxmox.clone.side_effect = RuntimeError("boom")

    await spawn_pass(
        conn=conn, proxmox=proxmox, github=github_client,
        cap=3, template_vmid=9000, vmid_range=(9100, 9199),
        runner_labels=["self-hosted", "lxc"],
    )

    row = conn.execute("SELECT * FROM runners WHERE job_id=42").fetchone()
    assert row["state"] == "failed"
    assert "boom" in row["last_error"]


async def test_spawn_pass_processes_only_up_to_slots(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=1)
    db.insert_pending_runner(conn, job_id=2)
    db.insert_pending_runner(conn, job_id=3)
    db.insert_pending_runner(conn, job_id=4)
    proxmox.allocate_vmid.side_effect = [9100, 9101, 9102]

    await spawn_pass(
        conn=conn, proxmox=proxmox, github=github_client,
        cap=3, template_vmid=9000, vmid_range=(9100, 9199),
        runner_labels=["self-hosted", "lxc"],
    )

    running = conn.execute(
        "SELECT COUNT(*) AS c FROM runners WHERE state='running'"
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM runners WHERE state='pending'"
    ).fetchone()["c"]
    assert running == 3
    assert pending == 1


async def test_cleanup_pass_destroys_completed(conn, proxmox):
    db.insert_pending_runner(conn, job_id=1)
    db.update_state_by_id(conn, runner_id=1, new_state="completed", vmid=9100)

    await cleanup_pass(conn=conn, proxmox=proxmox)

    proxmox.stop.assert_called_once_with(vmid=9100)
    proxmox.destroy.assert_called_once_with(vmid=9100)
    row = conn.execute("SELECT * FROM runners WHERE id=1").fetchone()
    assert row["state"] == "cleaned"
    assert row["cleaned_at"] is not None


async def test_cleanup_pass_marks_failed_on_error(conn, proxmox):
    db.insert_pending_runner(conn, job_id=1)
    db.update_state_by_id(conn, runner_id=1, new_state="completed", vmid=9100)
    proxmox.stop.side_effect = RuntimeError("locked")

    await cleanup_pass(conn=conn, proxmox=proxmox)

    row = conn.execute("SELECT * FROM runners WHERE id=1").fetchone()
    assert row["state"] == "failed"
    assert "locked" in row["last_error"]
