import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from controller import db

log = logging.getLogger(__name__)

_MIN_ORPHAN_AGE = timedelta(minutes=5)


async def reconcile_once(
    *,
    conn: sqlite3.Connection,
    proxmox,
    github,
    vmid_range: tuple[int, int],
    max_job_duration: timedelta,
) -> None:
    now = datetime.now(timezone.utc)
    proxmox_vmids = set(
        proxmox.list_lxcs_in_range(start=vmid_range[0], end=vmid_range[1])
    )
    db_rows = db.select_active_with_vmid(conn)
    db_vmids = {r["vmid"] for r in db_rows}

    # 1. Adopt orphans
    for vmid in proxmox_vmids - db_vmids:
        try:
            create_time = proxmox.get_create_time(vmid=vmid)
            if now - create_time < _MIN_ORPHAN_AGE:
                continue
            desc = proxmox.get_description(vmid=vmid)
            job_id = _parse_job_id(desc)
            if job_id is None:
                db.audit(conn, event="orphan_lxc_no_job_id", vmid=vmid)
                continue
            try:
                conn.execute(
                    "INSERT INTO runners (job_id, vmid, state, started_at) VALUES (?, ?, 'running', ?)",
                    (job_id, vmid, create_time.isoformat()),
                )
                db.audit(conn, event="adopted_orphan", job_id=job_id, vmid=vmid)
            except sqlite3.IntegrityError:
                pass  # row already exists
        except Exception:
            log.exception("reconciler adoption failed for vmid=%s", vmid)

    # 2. Reap ghost rows
    for row in db_rows:
        if row["vmid"] not in proxmox_vmids:
            db.update_state_by_id(
                conn, runner_id=row["id"], new_state="cleaned",
                cleaned_at=now,
            )
            db.audit(
                conn, event="reaped_ghost", job_id=row["job_id"], vmid=row["vmid"]
            )

    # 3. Reap timeouts
    for row in db.select_active_with_vmid(conn):
        started = datetime.fromisoformat(row["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if now - started < max_job_duration:
            continue
        try:
            proxmox.stop(vmid=row["vmid"])
            proxmox.destroy(vmid=row["vmid"])
        except Exception:
            log.exception("force-stop failed for vmid=%s", row["vmid"])
        db.update_state_by_id(
            conn, runner_id=row["id"], new_state="failed",
            last_error="timeout", cleaned_at=now,
        )
        db.audit(conn, event="reaped_timeout", job_id=row["job_id"], vmid=row["vmid"])

    # 4. Catch missed 'completed' webhooks
    for row in db.select_by_state(conn, "running"):
        started = datetime.fromisoformat(row["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if now - started < timedelta(minutes=5):
            continue
        if not row["repo"]:
            continue
        try:
            job = await github.get_workflow_job(repo=row["repo"], job_id=row["job_id"])
            if job.get("status") in ("completed", "cancelled"):
                db.update_state_by_id(conn, runner_id=row["id"], new_state="completed")
                db.audit(
                    conn, event="detected_completed_via_polling",
                    job_id=row["job_id"], vmid=row["vmid"],
                )
        except Exception:
            log.exception("github poll failed for job_id=%s", row["job_id"])


def _parse_job_id(description: str) -> int | None:
    for tok in description.split():
        if tok.startswith("job_id="):
            try:
                return int(tok[len("job_id="):])
            except ValueError:
                return None
    return None


async def run(
    *,
    conn,
    proxmox,
    github,
    vmid_range: tuple[int, int],
    max_job_duration: timedelta,
    interval: float = 300.0,
) -> None:
    while True:
        try:
            await reconcile_once(
                conn=conn, proxmox=proxmox, github=github,
                vmid_range=vmid_range, max_job_duration=max_job_duration,
            )
        except Exception:
            log.exception("reconciler tick failed")
        await asyncio.sleep(interval)
