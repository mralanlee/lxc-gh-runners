import sqlite3

import pytest

from controller import db


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_schema(c)
    yield c
    c.close()


def test_init_schema_creates_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "runners" in names
    assert "audit" in names


def test_insert_pending_runner(conn):
    rid = db.insert_pending_runner(conn, job_id=42)
    row = conn.execute("SELECT * FROM runners WHERE id=?", (rid,)).fetchone()
    assert row["job_id"] == 42
    assert row["state"] == "pending"
    assert row["vmid"] is None


def test_insert_pending_runner_duplicate_returns_none(conn):
    db.insert_pending_runner(conn, job_id=42)
    assert db.insert_pending_runner(conn, job_id=42) is None


def test_insert_pending_runner_with_repo(conn):
    db.insert_pending_runner(conn, job_id=99, repo="myorg/foo")
    row = conn.execute("SELECT * FROM runners WHERE job_id=99").fetchone()
    assert row["repo"] == "myorg/foo"


def test_update_state_by_job_id(conn):
    db.insert_pending_runner(conn, job_id=42)
    n = db.update_state_by_job_id(conn, job_id=42, new_state="running")
    assert n == 1
    row = conn.execute("SELECT state FROM runners WHERE job_id=42").fetchone()
    assert row["state"] == "running"


def test_update_state_by_job_id_missing_row_returns_zero(conn):
    assert db.update_state_by_job_id(conn, job_id=999, new_state="running") == 0


def test_count_active(conn):
    db.insert_pending_runner(conn, job_id=1)
    db.insert_pending_runner(conn, job_id=2)
    db.insert_pending_runner(conn, job_id=3)
    db.update_state_by_job_id(conn, job_id=1, new_state="spawning")
    db.update_state_by_job_id(conn, job_id=2, new_state="running")
    db.update_state_by_job_id(conn, job_id=3, new_state="completed")
    assert db.count_active(conn) == 3


def test_count_active_excludes_terminal_states(conn):
    db.insert_pending_runner(conn, job_id=1)
    db.update_state_by_job_id(conn, job_id=1, new_state="cleaned")
    db.insert_pending_runner(conn, job_id=2)
    db.update_state_by_job_id(conn, job_id=2, new_state="failed")
    assert db.count_active(conn) == 0


def test_select_pending_returns_oldest_first(conn):
    db.insert_pending_runner(conn, job_id=1)
    db.insert_pending_runner(conn, job_id=2)
    db.insert_pending_runner(conn, job_id=3)
    rows = db.select_pending(conn, limit=2)
    assert [r["job_id"] for r in rows] == [1, 2]


def test_audit_inserts_row(conn):
    db.audit(conn, event="webhook_received", job_id=42, vmid=None, detail="queued")
    row = conn.execute("SELECT * FROM audit").fetchone()
    assert row["event"] == "webhook_received"
    assert row["job_id"] == 42
    assert row["detail"] == "queued"


def test_update_state_by_job_id_no_op_when_cleaned(conn):
    db.insert_pending_runner(conn, job_id=42)
    db.update_state_by_job_id(conn, job_id=42, new_state="cleaned")
    n = db.update_state_by_job_id(conn, job_id=42, new_state="running")
    assert n == 0
    row = conn.execute("SELECT state FROM runners WHERE job_id=42").fetchone()
    assert row["state"] == "cleaned"


def test_update_state_by_job_id_no_op_when_failed(conn):
    db.insert_pending_runner(conn, job_id=42)
    db.update_state_by_job_id(conn, job_id=42, new_state="failed")
    n = db.update_state_by_job_id(conn, job_id=42, new_state="running")
    assert n == 0
