import asyncio
import logging
import sqlite3
from datetime import UTC, datetime

from controller import db

log = logging.getLogger(__name__)


async def spawn_pass(
    *,
    conn: sqlite3.Connection,
    proxmox,
    github,
    cap: int,
    template_vmid: int,
    vmid_range: tuple[int, int],
    runner_labels: list[str],
) -> None:
    slots = cap - db.count_active(conn)
    if slots <= 0:
        return
    pending = db.select_pending(conn, limit=slots)
    for row in pending:
        await _spawn_one(
            conn=conn,
            proxmox=proxmox,
            github=github,
            row=row,
            template_vmid=template_vmid,
            vmid_range=vmid_range,
            runner_labels=runner_labels,
        )


async def _spawn_one(*, conn, proxmox, github, row, template_vmid, vmid_range, runner_labels):
    runner_id = row["id"]
    job_id = row["job_id"]
    db.update_state_by_id(conn, runner_id=runner_id, new_state="spawning")
    db.audit(conn, event="spawn_started", job_id=job_id)
    vmid: int | None = None
    try:
        jit = await github.generate_jit_config(name=f"runner-{job_id}", labels=runner_labels)
        vmid = proxmox.allocate_vmid(start=vmid_range[0], end=vmid_range[1])
        proxmox.clone(template_vmid=template_vmid, new_vmid=vmid)
        now_iso = datetime.now(UTC).isoformat()
        proxmox.set_description(vmid=vmid, description=f"job_id={job_id} started_at={now_iso}")
        db.update_state_by_id(conn, runner_id=runner_id, new_state="spawning", vmid=vmid)
        proxmox.start(vmid=vmid)
        proxmox.wait_until_ready(vmid=vmid)
        proxmox.exec(
            vmid=vmid,
            cmd=[
                "sh",
                "-c",
                f"echo 'JITCONFIG={jit}' > /etc/runner.env && chmod 600 /etc/runner.env",
            ],
        )
        proxmox.exec(vmid=vmid, cmd=["systemctl", "start", "gha-runner.service"])
        db.update_state_by_id(conn, runner_id=runner_id, new_state="running")
        db.audit(conn, event="spawn_succeeded", job_id=job_id, vmid=vmid)
    except Exception as e:
        log.exception("spawn failed for job_id=%s", job_id)
        db.update_state_by_id(
            conn, runner_id=runner_id, new_state="failed", last_error=str(e), vmid=vmid
        )
        db.audit(conn, event="spawn_failed", job_id=job_id, vmid=vmid, detail=str(e))


async def cleanup_pass(*, conn, proxmox) -> None:
    rows = conn.execute(
        "SELECT * FROM runners "
        "WHERE vmid IS NOT NULL AND cleaned_at IS NULL "
        "AND state IN ('completed', 'failed')"
    ).fetchall()
    for row in rows:
        runner_id = row["id"]
        vmid = row["vmid"]
        job_id = row["job_id"]
        original_state = row["state"]
        try:
            proxmox.stop(vmid=vmid)
            proxmox.destroy(vmid=vmid)
            terminal_state = "cleaned" if original_state == "completed" else "failed"
            db.update_state_by_id(
                conn,
                runner_id=runner_id,
                new_state=terminal_state,
                cleaned_at=datetime.now(UTC),
            )
            db.audit(conn, event="cleanup_succeeded", job_id=job_id, vmid=vmid)
        except Exception as e:
            log.exception(
                "cleanup failed for job_id=%s vmid=%s state=%s",
                job_id,
                vmid,
                original_state,
            )
            # Only regress completed → failed on first error. On a row that's
            # already failed, leave the row alone and let the next tick retry.
            if original_state == "completed":
                db.update_state_by_id(
                    conn, runner_id=runner_id, new_state="failed", last_error=str(e)
                )
            db.audit(conn, event="cleanup_failed", job_id=job_id, vmid=vmid, detail=str(e))


async def run(
    *,
    conn,
    proxmox,
    github,
    cap: int,
    template_vmid: int,
    vmid_range: tuple[int, int],
    runner_labels: list[str],
    interval: float = 2.0,
) -> None:
    while True:
        try:
            await spawn_pass(
                conn=conn,
                proxmox=proxmox,
                github=github,
                cap=cap,
                template_vmid=template_vmid,
                vmid_range=vmid_range,
                runner_labels=runner_labels,
            )
            await cleanup_pass(conn=conn, proxmox=proxmox)
        except Exception:
            log.exception("worker tick failed")
        await asyncio.sleep(interval)
