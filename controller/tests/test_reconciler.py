import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from controller import db
from controller.reconciler import reconcile_once


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    db.init_schema(c)
    yield c
    c.close()


@pytest.fixture
def proxmox():
    return MagicMock()


@pytest.fixture
def github_client():
    g = MagicMock()
    g.get_workflow_job = AsyncMock(return_value={"status": "in_progress"})
    return g


async def test_adopts_orphan_lxc_with_job_id_in_description(conn, proxmox, github_client):
    proxmox.list_lxcs_in_range.return_value = [9100]
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    proxmox.get_create_time.return_value = old
    proxmox.get_description.return_value = f"job_id=42 started_at={old.isoformat()}"

    await reconcile_once(
        conn=conn, proxmox=proxmox, github=github_client,
        vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
    )

    row = conn.execute("SELECT * FROM runners WHERE job_id=42").fetchone()
    assert row is not None
    assert row["state"] == "running"
    assert row["vmid"] == 9100


async def test_skips_young_orphan(conn, proxmox, github_client):
    proxmox.list_lxcs_in_range.return_value = [9100]
    fresh = datetime.now(timezone.utc) - timedelta(minutes=2)
    proxmox.get_create_time.return_value = fresh

    await reconcile_once(
        conn=conn, proxmox=proxmox, github=github_client,
        vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
    )

    assert conn.execute("SELECT COUNT(*) AS c FROM runners").fetchone()["c"] == 0


async def test_skips_orphan_without_job_id_in_description(conn, proxmox, github_client):
    proxmox.list_lxcs_in_range.return_value = [9100]
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    proxmox.get_create_time.return_value = old
    proxmox.get_description.return_value = "no job_id here"

    await reconcile_once(
        conn=conn, proxmox=proxmox, github=github_client,
        vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
    )

    assert conn.execute("SELECT COUNT(*) AS c FROM runners").fetchone()["c"] == 0


async def test_reaps_ghost_db_row(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=1)
    db.update_state_by_id(conn, runner_id=1, new_state="running", vmid=9100)
    proxmox.list_lxcs_in_range.return_value = []  # vmid 9100 missing from proxmox

    await reconcile_once(
        conn=conn, proxmox=proxmox, github=github_client,
        vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
    )

    row = conn.execute("SELECT * FROM runners WHERE job_id=1").fetchone()
    assert row["state"] == "cleaned"
