import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from proxmoxer import ProxmoxAPI

from controller import db, reconciler, webhook, worker
from controller.config import Settings
from controller.github import GitHubClient
from controller.proxmox import ProxmoxClient


def _build_proxmox(settings: Settings) -> ProxmoxClient:
    user, token_name = settings.proxmox_token_id.split("!", 1)
    host = settings.proxmox_url.replace("https://", "").replace("http://", "")
    api = ProxmoxAPI(
        host,
        token_name=token_name,
        user=user,
        token_value=settings.proxmox_token_secret,
        verify_ssl=False,
        service="PVE",
    )
    return ProxmoxClient(
        api=api,
        node=settings.proxmox_node,
        ssh_host=settings.proxmox_host,
    )


def _build_github(settings: Settings) -> GitHubClient:
    return GitHubClient(pat=settings.github_pat, org=settings.github_org)


_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    logging.basicConfig(level=settings.log_level)

    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    proxmox_client = _build_proxmox(settings)
    github_client = _build_github(settings)

    _state["conn"] = conn
    _state["settings"] = settings

    app.include_router(
        webhook.build_router(
            conn=conn,
            secret=settings.github_webhook_secret,
            runner_labels=settings.runner_labels,
        )
    )

    worker_task = asyncio.create_task(
        worker.run(
            conn=conn, proxmox=proxmox_client, github=github_client,
            cap=settings.max_concurrent_runners,
            template_vmid=settings.template_vmid,
            vmid_range=(settings.runner_vmid_range_start, settings.runner_vmid_range_end),
            runner_labels=settings.runner_labels,
        )
    )
    reconciler_task = asyncio.create_task(
        reconciler.run(
            conn=conn, proxmox=proxmox_client, github=github_client,
            vmid_range=(settings.runner_vmid_range_start, settings.runner_vmid_range_end),
            max_job_duration=timedelta(hours=settings.max_job_duration_hours),
        )
    )

    try:
        yield
    finally:
        worker_task.cancel()
        reconciler_task.cancel()
        await asyncio.gather(worker_task, reconciler_task, return_exceptions=True)
        conn.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    conn = _state.get("conn")
    if conn is None:
        return {"states": {}}
    return {"states": db.select_state_counts(conn)}


@app.get("/audit")
async def audit_endpoint(job_id: int | None = None, limit: int = 100):
    conn = _state.get("conn")
    if conn is None:
        return []
    rows = db.select_audit(conn, job_id=job_id, limit=limit)
    return [dict(r) for r in rows]
