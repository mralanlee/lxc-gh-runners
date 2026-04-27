# Controller Service — Design

**Status:** Draft for implementation
**Date:** 2026-04-26
**Scope:** PRD 2 of the lxc-gh-runners project. PRD 1 (LXC template build) is out of scope; this document defines the contract this controller expects from the template.

## 1. Problem

Self-hosted GitHub Actions runners need to be ephemeral for security and reproducibility. Each `workflow_job` event from GitHub should result in a fresh LXC container that runs exactly one job, then is destroyed. We need a service that turns webhooks into LXCs and cleans them up.

## 2. Goals

- One Python service: webhook receiver + worker + reconciler in a single process.
- SQLite for durable state.
- Deploys as a Docker container running inside an LXC on the Proxmox host.
- Survives restarts: LXCs in flight are adopted, not orphaned.
- Stays within a configurable concurrency cap.
- Reconciler reaps drift every 5 minutes (orphan LXCs, timed-out jobs, missed `completed` webhooks).

## 3. Non-goals

- GitHub App authentication. PAT only.
- Webhook event idempotency table. The `runners.job_id` `UNIQUE` constraint catches duplicates at the DB layer.
- Worker retry logic. The reconciler is the safety net.
- SQLite backup. State is rebuilt from Proxmox on cold start (see §10).
- Building the LXC template itself. PRD 1 owns that, against the contract in §13.

## 4. Architecture

```
controller/  (Docker container, inside an LXC on the Proxmox host)
├── FastAPI app       ← POST /webhook/github   (verify sig + INSERT only)
├── Worker task       ← asyncio loop, every ~2s, drains pending + cleans completed
└── Reconciler task   ← asyncio loop, every 5min, reaps drift
        ↓ all three share ↓
   SQLite (file in a docker volume; durable across restarts)
        ↓
   Proxmox HTTPS API (proxmoxer, token auth)  +  GitHub REST (httpx, PAT)
```

All three units run in the same Python process. The worker and reconciler are launched from FastAPI's `lifespan` as background asyncio tasks. The webhook handler does no Proxmox or GitHub work — it only verifies, INSERTs, and returns 200.

## 5. Project layout

```
controller/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                  # uv for install/lock
├── .env.example
├── src/controller/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app + lifespan launches background tasks
│   ├── config.py                   # pydantic-settings
│   ├── db.py                       # sqlite3 connection, schema bootstrap, helpers
│   ├── proxmox.py                  # proxmoxer wrapper: clone/start/stop/destroy/exec/list/set_description
│   ├── github.py                   # JIT config, signature verification, job-status lookup
│   ├── webhook.py                  # FastAPI router for /webhook/github and /health
│   ├── worker.py                   # spawn pass + cleanup pass
│   └── reconciler.py               # 5-min sweep
└── tests/
    ├── conftest.py
    ├── test_webhook.py
    ├── test_worker.py
    ├── test_reconciler.py
    └── test_state_transitions.py
```

## 6. Configuration

Read from env vars (or `.env` for dev) via `pydantic-settings`.

| Var | Purpose | Example |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC-SHA256 secret for signature verification | `s3cret` |
| `GITHUB_PAT` | PAT with `admin:org` scope, used for JIT config + job lookup | `ghp_...` |
| `GITHUB_ORG` | Org slug | `myorg` |
| `RUNNER_LABELS` | Comma-separated labels the runner registers with | `self-hosted,lxc` |
| `PROXMOX_URL` | Proxmox API URL | `https://localhost:8006` |
| `PROXMOX_TOKEN_ID` | API token id | `controller@pve!ctrl` |
| `PROXMOX_TOKEN_SECRET` | API token secret | `...` |
| `PROXMOX_NODE` | Node name | `pve` |
| `TEMPLATE_VMID` | Template LXC to clone | `9000` |
| `RUNNER_VMID_RANGE_START` | Inclusive start of VMID pool | `9100` |
| `RUNNER_VMID_RANGE_END` | Inclusive end of VMID pool | `9199` |
| `MAX_CONCURRENT_RUNNERS` | Cap on `spawning + running + completed` rows | `3` |
| `MAX_JOB_DURATION_HOURS` | Reconciler timeout threshold | `6` |
| `DB_PATH` | SQLite file path | `/data/controller.sqlite` |
| `LOG_LEVEL` | `INFO` / `DEBUG` | `INFO` |

## 7. Data model

```sql
CREATE TABLE runners (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id      INTEGER UNIQUE NOT NULL,           -- workflow_job.id
  vmid        INTEGER UNIQUE,                    -- NULL until spawned
  state       TEXT NOT NULL,                     -- see §8
  started_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cleaned_at  TIMESTAMP,
  last_error  TEXT
);
CREATE INDEX idx_runners_state ON runners(state);

CREATE TABLE audit (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  job_id      INTEGER,
  vmid        INTEGER,
  event       TEXT NOT NULL,
  detail      TEXT
);
CREATE INDEX idx_audit_job_id ON audit(job_id);
CREATE INDEX idx_audit_ts ON audit(ts);
```

The `audit` table has no retention policy in v1; row volume is small at the configured concurrency. A reconciler-driven cleanup can be added later if needed.

Schema bootstrap runs idempotently on app startup (CREATE TABLE IF NOT EXISTS).

## 8. State machine

```
        ┌──────────────────────────────┐
        │                              ▼
   pending → spawning → running → completed → cleaned
                  ↓        ↓          ↓
                failed   failed     failed
```

| State | Set by | Meaning |
|---|---|---|
| `pending` | webhook handler | `queued` event received, awaiting worker capacity |
| `spawning` | worker | claimed by worker, clone/start/exec in progress |
| `running` | worker (post-exec) **or** webhook handler (`in_progress`) | LXC is up, runner registered, job underway |
| `completed` | webhook handler (`completed`) **or** reconciler | GitHub reports job finished, awaiting cleanup |
| `cleaned` | worker cleanup pass | LXC stopped + destroyed, terminal success |
| `failed` | worker or reconciler | terminal error; `last_error` set |

`UPDATE`s to `running` from the webhook are idempotent and may race with the worker's own transition — order doesn't matter, last-write-wins on the same value.

## 9. Webhook flow

`POST /webhook/github` is fast and side-effect-light:

```
1. Verify X-Hub-Signature-256 (HMAC-SHA256 over raw body, GITHUB_WEBHOOK_SECRET)
   → 401 on mismatch
2. Parse JSON; if event header != "workflow_job" → 200, ignore
3. If the job's labels are not a subset of RUNNER_LABELS → 200, ignore. (GitHub's match rule: a runner picks up a job iff the runner has every label the job requires. We mirror that check here so we only spawn for jobs our runner can actually serve.)
4. Switch on payload.action:
     "queued"      → INSERT runner(job_id, state='pending')   [UNIQUE catches duplicate]
     "in_progress" → UPDATE state='running' WHERE job_id=…    [no-op if state already terminal]
     "completed"   → UPDATE state='completed' WHERE job_id=…  [no-op if state='cleaned'/'failed']
5. audit(event, job_id=…, detail=action)
6. Return 200
```

The handler does no network I/O beyond what FastAPI does itself — no Proxmox, no GitHub. This keeps webhook latency to a small DB write.

## 10. Worker

Runs as one asyncio task. Each tick (~2 seconds) does a spawn pass then a cleanup pass.

### 10.1 Spawn pass

```
count_active = SELECT COUNT(*) FROM runners WHERE state IN ('spawning','running','completed')
slots = MAX_CONCURRENT_RUNNERS - count_active
if slots <= 0: return

for row in SELECT * FROM runners WHERE state='pending' ORDER BY id LIMIT slots:
    UPDATE state='spawning' WHERE id=row.id           # claim
    audit('spawn_started', job_id=row.job_id)
    try:
        jit  = github.generate_jit_config(name=f"runner-{row.job_id}", labels=RUNNER_LABELS)
        vmid = proxmox.allocate_vmid()                # lowest free in range
        proxmox.clone(TEMPLATE_VMID, vmid)
        proxmox.set_description(vmid, f"job_id={row.job_id} started_at={now_iso}")
        UPDATE vmid=vmid WHERE id=row.id              # persist before start
        proxmox.start(vmid)
        proxmox.wait_until_ready(vmid)                # poll status; small grace; retry first exec
        proxmox.exec(vmid, ["sh","-c", f"echo 'JITCONFIG={jit}' > /etc/runner.env && chmod 600 /etc/runner.env"])
        proxmox.exec(vmid, ["systemctl","start","gha-runner.service"])
        UPDATE state='running' WHERE id=row.id
        audit('spawn_succeeded', job_id=row.job_id, vmid=vmid)
    except Exception as e:
        UPDATE state='failed', last_error=str(e) WHERE id=row.id
        audit('spawn_failed', job_id=row.job_id, vmid=row.vmid, detail=str(e))
        # leave any LXC behind; reconciler will reap
```

VMID allocation: list all VMIDs on the configured node within `[RANGE_START, RANGE_END]`, pick the lowest gap. Deterministic and easy to reason about during debugging.

### 10.2 Cleanup pass

```
for row in SELECT * FROM runners WHERE state='completed':
    try:
        proxmox.stop(row.vmid, force=True)
        proxmox.destroy(row.vmid)
        UPDATE state='cleaned', cleaned_at=now WHERE id=row.id
        audit('cleanup_succeeded', job_id=row.job_id, vmid=row.vmid)
    except Exception as e:
        UPDATE state='failed', last_error=str(e) WHERE id=row.id
        audit('cleanup_failed', job_id=row.job_id, vmid=row.vmid, detail=str(e))
```

## 11. Reconciler

Runs every 5 minutes. Skips LXCs younger than 5 minutes to avoid racing the worker.

```
proxmox_vmids = proxmox.list_lxcs_in_range(START, END)
db_vmids      = SELECT vmid FROM runners WHERE vmid IS NOT NULL AND state != 'cleaned'

# 1. Adopt orphan LXCs (Proxmox has it, DB doesn't) — supports cold-start from empty DB
for vmid in proxmox_vmids - db_vmids:
    if (now - proxmox.get_create_time(vmid)) < 5 minutes: continue
    desc   = proxmox.get_description(vmid)
    job_id = parse_job_id(desc)
    if job_id is None:
        audit('orphan_lxc_no_job_id', vmid=vmid)
        continue
    INSERT runner(job_id, vmid, state='running', started_at=create_time) ON CONFLICT DO NOTHING
    audit('adopted_orphan', job_id=job_id, vmid=vmid)

# 2. Reap ghost rows (DB says vmid X, Proxmox doesn't have it)
for row in SELECT * FROM runners WHERE vmid NOT IN proxmox_vmids AND state IN ('spawning','running','completed'):
    UPDATE state='cleaned', cleaned_at=now WHERE id=row.id
    audit('reaped_ghost', job_id=row.job_id, vmid=row.vmid)

# 3. Reap timeouts
for row in SELECT * FROM runners WHERE state IN ('running','completed') AND started_at < now - MAX_JOB_DURATION_HOURS:
    proxmox.stop(row.vmid, force=True)
    proxmox.destroy(row.vmid)
    UPDATE state='failed', last_error='timeout', cleaned_at=now WHERE id=row.id
    audit('reaped_timeout', job_id=row.job_id, vmid=row.vmid)

# 4. Catch missed 'completed' webhooks
for row in SELECT * FROM runners WHERE state='running' AND age > 5min:
    status = github.get_workflow_job(row.job_id).status
    if status in ('completed','cancelled'):
        UPDATE state='completed' WHERE id=row.id      # worker cleanup pass picks up next tick
        audit('detected_completed_via_polling', job_id=row.job_id)
```

### 11.1 Cold-start state reconstruction

If the SQLite file is lost, the reconciler's adoption step rebuilds the live state on the next tick: it walks LXCs in the VMID range, parses `job_id` from the description, and INSERTs `runners` rows. Jobs with `state='pending'` that arrived during the downtime are *not* recoverable — those webhook events are dropped. Acceptable per PRD.

## 12. Error handling

| Failure | Response |
|---|---|
| Webhook signature invalid | 401, no log spam beyond `audit('webhook_bad_sig')` |
| Webhook for unknown event type | 200, ignored |
| Duplicate `job_id` INSERT | UNIQUE violation caught, debug log, 200 |
| `proxmox.exec` first-call timeout | retry once after 2s; on second fail → `state='failed'` |
| `proxmox.clone` fails | `state='failed'`; clone is atomic so no LXC to clean |
| `proxmox.start` fails | `state='failed'`; reconciler reaps the cloned-but-stopped LXC |
| GitHub JIT-config call fails | `state='failed'` before VMID allocation |
| SQLite locked / disk full | crash loudly; let Docker restart the container |
| Process killed mid-spawn | reconciler adopts via description on next start |

## 13. Template contract (input from PRD 1)

The controller expects the LXC at `TEMPLATE_VMID` to provide:

- `actions/runner` installed at `/opt/actions-runner/` (or any path; the systemd unit knows where it lives).
- A systemd unit named `gha-runner.service` that:
  - Reads `EnvironmentFile=/etc/runner.env`.
  - Starts the runner with `--jitconfig "$JITCONFIG"` (one-shot ephemeral mode).
  - Is **disabled** in the template (`systemctl disable gha-runner.service`) so it does not auto-start at clone-boot. The controller starts it explicitly via `pct exec` after writing `/etc/runner.env`.
- Network configured to reach `api.github.com` (DHCP or static) on first boot.
- A non-root user that the runner runs as (set in the unit file). Root works in v1 if simpler.

The controller writes `/etc/runner.env` containing exactly one line: `JITCONFIG=<base64-string-from-github>`, mode `0600`.

## 14. Deployment

- **Base image:** `python:3.12-slim`.
- **Install:** `uv pip install --system .` from `pyproject.toml`.
- **Entrypoint:** `uvicorn controller.main:app --host 0.0.0.0 --port 8000`.
- **Runtime location:** Docker container inside an LXC on the Proxmox host. The LXC needs:
  - Network reach to the Proxmox API (`https://localhost:8006` or the host IP on the management network).
  - Outbound HTTPS to `api.github.com`.
  - Inbound port for the webhook (proxied via the host or exposed directly, depending on network setup).
- **Volumes:**
  - `/data` for the SQLite file.
  - `.env` mounted read-only.
- **Healthcheck:** `GET /health` → returns DB row counts by state.

## 15. Testing

- **Unit tests (pytest, async):** mock `controller.proxmox` and `controller.github`; cover signature verification, state-transition logic, cap enforcement, reconciler decisions.
- **End-to-end test in CI:** `httpx.AsyncClient` against the FastAPI app with dependency-overrides supplying fake Proxmox + GitHub clients. Drives a full webhook → spawn → in_progress → completed → cleanup path.
- **Manual smoke test:** documented in README. Push a workflow with `runs-on: [self-hosted, lxc]`, watch logs, confirm LXC spawns and is destroyed.
- **No live-Proxmox CI test.** That's a manual step on real hardware.

## 16. Observability

- **Structured logs** via `structlog` or stdlib JSON formatter.
- Each state transition logs `job_id`, `vmid`, old state, new state.
- `GET /health` → JSON of `{state: count}` over the `runners` table; used for liveness and quick debugging.
- `GET /audit?job_id=<id>&limit=100` → recent audit rows, JSON. Useful for "what happened to job X."

## 17. Spike items / verify during implementation

- **Proxmox REST `exec` endpoint.** I am not certain `POST /nodes/{node}/lxc/{vmid}/status/exec` exists in the current Proxmox REST API; this needs verifying first. If the endpoint is CLI-only (`pct exec`), fall back to SSH from the controller container to the host. The fallback lives behind the same `proxmox.exec()` interface so no other module changes.
- **`wait_until_ready` heuristic.** Confirm a polling-on-status + small grace + first-exec-with-retry is reliable; tune the grace if not.
- **GitHub PAT scope.** Confirm `admin:org` is sufficient for `generate-jitconfig`; switch to fine-grained `Self-hosted runners: write` if available and equivalent.
