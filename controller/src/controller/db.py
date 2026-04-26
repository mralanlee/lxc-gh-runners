import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runners (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id      INTEGER UNIQUE NOT NULL,
  repo        TEXT,
  vmid        INTEGER UNIQUE,
  state       TEXT NOT NULL,
  started_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cleaned_at  TIMESTAMP,
  last_error  TEXT
);
CREATE INDEX IF NOT EXISTS idx_runners_state ON runners(state);

CREATE TABLE IF NOT EXISTS audit (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  job_id INTEGER,
  vmid   INTEGER,
  event  TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_job_id ON audit(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""

ACTIVE_STATES = ("spawning", "running", "completed")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def insert_pending_runner(
    conn: sqlite3.Connection, *, job_id: int, repo: str | None = None
) -> int | None:
    try:
        cur = conn.execute(
            "INSERT INTO runners (job_id, repo, state) VALUES (?, ?, 'pending')",
            (job_id, repo),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def update_state_by_job_id(
    conn: sqlite3.Connection, *, job_id: int, new_state: str
) -> int:
    cur = conn.execute(
        "UPDATE runners SET state=? WHERE job_id=? AND state NOT IN ('cleaned', 'failed')",
        (new_state, job_id),
    )
    return cur.rowcount


def update_state_by_id(
    conn: sqlite3.Connection,
    *,
    runner_id: int,
    new_state: str,
    vmid: int | None = None,
    last_error: str | None = None,
    cleaned_at: datetime | None = None,
) -> int:
    sets = ["state=?"]
    args: list = [new_state]
    if vmid is not None:
        sets.append("vmid=?")
        args.append(vmid)
    if last_error is not None:
        sets.append("last_error=?")
        args.append(last_error)
    if cleaned_at is not None:
        sets.append("cleaned_at=?")
        args.append(cleaned_at.isoformat())
    args.append(runner_id)
    cur = conn.execute(
        f"UPDATE runners SET {', '.join(sets)} WHERE id=?", args
    )
    return cur.rowcount


def count_active(conn: sqlite3.Connection) -> int:
    placeholders = ",".join("?" * len(ACTIVE_STATES))
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM runners WHERE state IN ({placeholders})",
        ACTIVE_STATES,
    ).fetchone()
    return row["c"]


def select_pending(conn: sqlite3.Connection, *, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM runners WHERE state='pending' ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()


def select_by_state(conn: sqlite3.Connection, state: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM runners WHERE state=? ORDER BY id", (state,)
    ).fetchall()


def select_active_with_vmid(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(ACTIVE_STATES))
    return conn.execute(
        f"SELECT * FROM runners WHERE vmid IS NOT NULL AND state IN ({placeholders})",
        ACTIVE_STATES,
    ).fetchall()


def select_state_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT state, COUNT(*) AS c FROM runners GROUP BY state"
    ).fetchall()
    return {r["state"]: r["c"] for r in rows}


def select_audit(
    conn: sqlite3.Connection, *, job_id: int | None = None, limit: int = 100
) -> list[sqlite3.Row]:
    if job_id is None:
        return conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM audit WHERE job_id=? ORDER BY id DESC LIMIT ?",
        (job_id, limit),
    ).fetchall()


def audit(
    conn: sqlite3.Connection,
    *,
    event: str,
    job_id: int | None = None,
    vmid: int | None = None,
    detail: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit (event, job_id, vmid, detail) VALUES (?, ?, ?, ?)",
        (event, job_id, vmid, detail),
    )
