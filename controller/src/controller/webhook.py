import json
import sqlite3

from fastapi import APIRouter, Header, HTTPException, Request

from controller import db, github


def build_router(*, conn: sqlite3.Connection, secret: str, runner_labels: list[str]) -> APIRouter:
    router = APIRouter()
    label_set = set(runner_labels)

    @router.post("/webhook/github")
    async def receive(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_github_event: str | None = Header(default=None),
    ):
        body = await request.body()
        if not github.verify_signature(secret=secret, body=body, header=x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid signature")
        if x_github_event != "workflow_job":
            return {"ok": True, "ignored": "event"}
        payload = json.loads(body)
        job = payload.get("workflow_job") or {}
        job_id = job.get("id")
        labels = set(job.get("labels", []))
        action = payload.get("action")
        if not label_set.issubset(labels):
            return {"ok": True, "ignored": "labels"}
        if not job_id or not action:
            return {"ok": True, "ignored": "missing fields"}
        if action == "queued":
            repo = (payload.get("repository") or {}).get("full_name")
            inserted = db.insert_pending_runner(conn, job_id=job_id, repo=repo)
            db.audit(conn, event="webhook_queued", job_id=job_id, detail="duplicate" if inserted is None else None)
        elif action == "in_progress":
            db.update_state_by_job_id(conn, job_id=job_id, new_state="running")
            db.audit(conn, event="webhook_in_progress", job_id=job_id)
        elif action == "completed":
            db.update_state_by_job_id(conn, job_id=job_id, new_state="completed")
            db.audit(conn, event="webhook_completed", job_id=job_id)
        return {"ok": True}

    return router
