# Controller Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single Python service that turns GitHub `workflow_job` webhooks into ephemeral LXC runners on Proxmox and reaps them when jobs finish.

**Architecture:** One FastAPI process running three concurrent units (webhook receiver, worker, reconciler) over a shared SQLite file. Deploys as a Docker container inside an LXC on the Proxmox host. Talks to Proxmox via the HTTPS API (proxmoxer) and to GitHub via REST (httpx + PAT).

**Tech Stack:** Python 3.12, FastAPI, uvicorn, proxmoxer, httpx, pydantic-settings, sqlite3 (stdlib), pytest, pytest-asyncio, respx, uv.

**Spec:** `docs/superpowers/specs/2026-04-26-controller-service-design.md`

---

## File Structure

```
controller/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── README.md
├── src/controller/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + lifespan launches background tasks
│   ├── config.py            # pydantic-settings
│   ├── db.py                # sqlite3 connection, schema bootstrap, audit helper, query helpers
│   ├── proxmox.py           # proxmoxer wrapper
│   ├── github.py            # signature verification, JIT config, job-status lookup
│   ├── webhook.py           # FastAPI router for /webhook/github
│   ├── worker.py            # spawn pass + cleanup pass + loop
│   └── reconciler.py        # 5-min sweep + loop
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_db.py
    ├── test_github.py
    ├── test_proxmox.py
    ├── test_webhook.py
    ├── test_worker.py
    ├── test_reconciler.py
    └── test_e2e.py
```

Each module has one responsibility. Webhook does no I/O beyond DB. Worker and reconciler are the only modules that talk to Proxmox or GitHub for state-changing actions. `db.py` owns all SQL.

---

## Task 1: Spike — verify the Proxmox `exec` REST endpoint

**Files:**
- Create: `controller/spike-notes.md` (committed; deleted at end of plan)

This spike resolves an open question from the spec (§17): does Proxmox VE 8.x expose `pct exec` over the REST API, and does proxmoxer support it? The answer determines the implementation of `controller/proxmox.py:exec()`. The interface stays the same either way.

- [ ] **Step 1: Read Proxmox docs**

Open `https://pve.proxmox.com/pve-docs/api-viewer/index.html` (or check the local Proxmox host's API viewer at `https://<host>:8006/api2/json/`). Search for `lxc` endpoints. Look specifically for any `exec`, `command`, or shell-related path under `/nodes/{node}/lxc/{vmid}/`.

- [ ] **Step 2: Check proxmoxer source for exec support**

```bash
pip download proxmoxer --no-deps -d /tmp/proxmoxer-src && \
  cd /tmp/proxmoxer-src && \
  unzip *.whl -d /tmp/proxmoxer-extracted
grep -rn "exec" /tmp/proxmoxer-extracted/proxmoxer/
```

Note any methods like `.exec.post(...)` on LXCs.

- [ ] **Step 3: If REST exec is unavailable, prepare SSH fallback plan**

If neither the REST API nor proxmoxer supports LXC exec, the implementation will:
- SSH from the container to the Proxmox host using a key mounted at `/etc/controller/proxmox_ssh_key`.
- Run `pct exec <vmid> -- <cmd>` over SSH.
- Use `paramiko` (add to deps) or stdlib `subprocess` calling `ssh`.

- [ ] **Step 4: Write spike-notes.md with the decision**

```markdown
# Spike: Proxmox LXC exec
- REST endpoint exists: yes/no (cite path)
- proxmoxer support: yes/no (cite method)
- Decision: [REST | SSH]
- Implementation note for proxmox.exec(): [...]
```

- [ ] **Step 5: Commit**

```bash
git add controller/spike-notes.md
git commit -m "spike: verify proxmox lxc exec api surface"
```

---

## Task 2: Bootstrap project skeleton

**Files:**
- Create: `controller/pyproject.toml`
- Create: `controller/Dockerfile`
- Create: `controller/docker-compose.yml`
- Create: `controller/.env.example`
- Create: `controller/.dockerignore`
- Create: `controller/.gitignore`
- Create: `controller/src/controller/__init__.py`
- Create: `controller/tests/__init__.py`
- Create: `controller/tests/conftest.py`

- [ ] **Step 1: Create `controller/pyproject.toml`**

```toml
[project]
name = "controller"
version = "0.1.0"
description = "GitHub Actions LXC runner controller"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "proxmoxer>=2.0",
    "requests>=2.31",
    "httpx>=0.27",
    "pydantic-settings>=2.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.20",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/controller"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create `controller/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/

RUN uv pip install --system .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "controller.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create `controller/docker-compose.yml`**

```yaml
services:
  controller:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
    ports:
      - "8000:8000"
```

- [ ] **Step 4: Create `controller/.env.example`**

```bash
GITHUB_WEBHOOK_SECRET=changeme
GITHUB_PAT=ghp_changeme
GITHUB_ORG=myorg
RUNNER_LABELS=self-hosted,lxc

PROXMOX_URL=https://localhost:8006
PROXMOX_TOKEN_ID=controller@pve!ctrl
PROXMOX_TOKEN_SECRET=changeme
PROXMOX_NODE=pve

TEMPLATE_VMID=9000
RUNNER_VMID_RANGE_START=9100
RUNNER_VMID_RANGE_END=9199
MAX_CONCURRENT_RUNNERS=3
MAX_JOB_DURATION_HOURS=6

DB_PATH=/data/controller.sqlite
LOG_LEVEL=INFO
```

- [ ] **Step 5: Create `controller/.dockerignore`**

```
.git
.venv
data/
__pycache__/
*.pyc
.env
tests/
```

- [ ] **Step 6: Create `controller/.gitignore`**

```
.venv/
__pycache__/
*.pyc
data/
.env
*.egg-info/
dist/
build/
```

- [ ] **Step 7: Create empty package and test files**

`controller/src/controller/__init__.py`:
```python
```

`controller/tests/__init__.py`:
```python
```

`controller/tests/conftest.py`:
```python
import pytest


@pytest.fixture
def env_overrides(monkeypatch):
    """Set the minimum env vars needed to construct Settings()."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("GITHUB_PAT", "ghp_test")
    monkeypatch.setenv("GITHUB_ORG", "testorg")
    monkeypatch.setenv("RUNNER_LABELS", "self-hosted,lxc")
    monkeypatch.setenv("PROXMOX_URL", "https://prox.test:8006")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "ctrl@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "tok")
    monkeypatch.setenv("PROXMOX_NODE", "pve")
    monkeypatch.setenv("TEMPLATE_VMID", "9000")
    monkeypatch.setenv("RUNNER_VMID_RANGE_START", "9100")
    monkeypatch.setenv("RUNNER_VMID_RANGE_END", "9199")
    monkeypatch.setenv("MAX_CONCURRENT_RUNNERS", "3")
    monkeypatch.setenv("MAX_JOB_DURATION_HOURS", "6")
    monkeypatch.setenv("DB_PATH", ":memory:")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
```

- [ ] **Step 8: Verify install works**

Run: `cd controller && uv pip install --system -e ".[dev]"`
Expected: clean install, no errors.

Run: `cd controller && pytest --collect-only`
Expected: no tests yet, exit code 5.

- [ ] **Step 9: Commit**

```bash
git add controller/
git commit -m "feat: bootstrap controller project skeleton"
```

---

## Task 3: Config module

**Files:**
- Create: `controller/src/controller/config.py`
- Create: `controller/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`controller/tests/test_config.py`:
```python
from controller.config import Settings


def test_settings_loads_from_env(env_overrides):
    s = Settings()
    assert s.github_org == "testorg"
    assert s.runner_labels == ["self-hosted", "lxc"]
    assert s.template_vmid == 9000
    assert s.runner_vmid_range_start == 9100
    assert s.max_concurrent_runners == 3
    assert s.proxmox_url == "https://prox.test:8006"


def test_runner_labels_split_on_comma_and_strip(monkeypatch, env_overrides):
    monkeypatch.setenv("RUNNER_LABELS", "  self-hosted , lxc , gpu  ")
    s = Settings()
    assert s.runner_labels == ["self-hosted", "lxc", "gpu"]
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_config.py -v`
Expected: ImportError for `controller.config`.

- [ ] **Step 3: Implement `controller/src/controller/config.py`**

```python
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    github_webhook_secret: str
    github_pat: str
    github_org: str
    runner_labels: list[str]

    proxmox_url: str
    proxmox_token_id: str
    proxmox_token_secret: str
    proxmox_node: str

    template_vmid: int
    runner_vmid_range_start: int
    runner_vmid_range_end: int
    max_concurrent_runners: int = 3
    max_job_duration_hours: int = 6

    db_path: str = "/data/controller.sqlite"
    log_level: str = "INFO"

    @field_validator("runner_labels", mode="before")
    @classmethod
    def split_labels(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/config.py controller/tests/test_config.py
git commit -m "feat(controller): add config module"
```

---

## Task 4: DB module — schema, audit helper, query helpers

**Files:**
- Create: `controller/src/controller/db.py`
- Create: `controller/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_db.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/db.py`**

```python
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

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
        "UPDATE runners SET state=? WHERE job_id=?", (new_state, job_id)
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
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_db.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/db.py controller/tests/test_db.py
git commit -m "feat(controller): add db module with schema, helpers, audit"
```

---

## Task 5: GitHub module — signature verification

**Files:**
- Create: `controller/src/controller/github.py`
- Create: `controller/tests/test_github.py`

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_github.py`:
```python
import hashlib
import hmac

from controller import github


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def test_verify_signature_valid():
    body = b'{"foo":"bar"}'
    sig = _sign("topsecret", body)
    assert github.verify_signature(secret="topsecret", body=body, header=sig) is True


def test_verify_signature_wrong_secret():
    body = b'{"foo":"bar"}'
    sig = _sign("other", body)
    assert github.verify_signature(secret="topsecret", body=body, header=sig) is False


def test_verify_signature_missing_header():
    assert (
        github.verify_signature(secret="topsecret", body=b"{}", header=None) is False
    )


def test_verify_signature_malformed_header():
    assert (
        github.verify_signature(secret="topsecret", body=b"{}", header="garbage")
        is False
    )
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_github.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/github.py` (signature only — JIT/job lookup added next task)**

```python
import hashlib
import hmac


def verify_signature(*, secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header[len("sha256="):]
    return hmac.compare_digest(expected, received)
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_github.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/github.py controller/tests/test_github.py
git commit -m "feat(controller): add github webhook signature verification"
```

---

## Task 6: GitHub module — JIT config + job lookup

**Files:**
- Modify: `controller/src/controller/github.py`
- Modify: `controller/tests/test_github.py`

- [ ] **Step 1: Add the failing tests**

Append to `controller/tests/test_github.py`:
```python
import httpx
import pytest
import respx

from controller.github import GitHubClient


@pytest.fixture
def client():
    return GitHubClient(pat="ghp_test", org="myorg")


@respx.mock
async def test_generate_jit_config(client):
    route = respx.post(
        "https://api.github.com/orgs/myorg/actions/runners/generate-jitconfig"
    ).mock(return_value=httpx.Response(201, json={"encoded_jit_config": "JITSTRING"}))
    jit = await client.generate_jit_config(
        name="runner-42", labels=["self-hosted", "lxc"]
    )
    assert jit == "JITSTRING"
    assert route.called
    sent = route.calls.last.request
    assert b"runner-42" in sent.content
    assert b"self-hosted" in sent.content


@respx.mock
async def test_get_workflow_job(client):
    respx.get(
        "https://api.github.com/repos/myorg/anyrepo/actions/jobs/42"
    ).mock(return_value=httpx.Response(200, json={"id": 42, "status": "completed", "conclusion": "success"}))
    job = await client.get_workflow_job(repo="myorg/anyrepo", job_id=42)
    assert job["status"] == "completed"


@respx.mock
async def test_generate_jit_config_http_error(client):
    respx.post(
        "https://api.github.com/orgs/myorg/actions/runners/generate-jitconfig"
    ).mock(return_value=httpx.Response(422, json={"message": "bad labels"}))
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_jit_config(name="runner-1", labels=["x"])
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_github.py::test_generate_jit_config -v`
Expected: ImportError for `GitHubClient`.

- [ ] **Step 3: Add `GitHubClient` to `controller/src/controller/github.py`**

Append:
```python
import httpx


class GitHubClient:
    def __init__(self, *, pat: str, org: str):
        self._pat = pat
        self._org = org
        self._headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def generate_jit_config(self, *, name: str, labels: list[str]) -> str:
        url = f"https://api.github.com/orgs/{self._org}/actions/runners/generate-jitconfig"
        payload = {
            "name": name,
            "runner_group_id": 1,
            "labels": labels,
            "work_folder": "_work",
        }
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(url, headers=self._headers, json=payload)
            r.raise_for_status()
            return r.json()["encoded_jit_config"]

    async def get_workflow_job(self, *, repo: str, job_id: int) -> dict:
        url = f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}"
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(url, headers=self._headers)
            r.raise_for_status()
            return r.json()
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_github.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/github.py controller/tests/test_github.py
git commit -m "feat(controller): add github jit config + job lookup"
```

---

## Task 7: Proxmox module — basic operations

**Files:**
- Create: `controller/src/controller/proxmox.py`
- Create: `controller/tests/test_proxmox.py`

This task implements the operations that don't require `pct exec`: clone, start, stop, destroy, list, get/set description, allocate VMID. Task 8 adds exec + ready-polling.

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_proxmox.py`:
```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from controller.proxmox import ProxmoxClient


@pytest.fixture
def fake_api():
    """Build a MagicMock shaped like proxmoxer's ProxmoxAPI."""
    api = MagicMock()
    return api


@pytest.fixture
def client(fake_api):
    return ProxmoxClient(api=fake_api, node="pve")


def test_list_lxcs_in_range_filters_by_vmid(client, fake_api):
    fake_api.nodes.return_value.lxc.get.return_value = [
        {"vmid": "9050", "status": "running"},
        {"vmid": "9100", "status": "running"},
        {"vmid": "9150", "status": "stopped"},
        {"vmid": "9200", "status": "running"},
    ]
    result = client.list_lxcs_in_range(start=9100, end=9199)
    assert sorted(result) == [9100, 9150]


def test_allocate_vmid_returns_lowest_free(client, fake_api):
    fake_api.nodes.return_value.lxc.get.return_value = [
        {"vmid": "9100", "status": "running"},
        {"vmid": "9102", "status": "running"},
    ]
    assert client.allocate_vmid(start=9100, end=9199) == 9101


def test_allocate_vmid_raises_when_full(client, fake_api):
    fake_api.nodes.return_value.lxc.get.return_value = [
        {"vmid": str(v), "status": "running"} for v in range(9100, 9105)
    ]
    with pytest.raises(RuntimeError, match="no free VMID"):
        client.allocate_vmid(start=9100, end=9104)


def test_clone_calls_api(client, fake_api):
    client.clone(template_vmid=9000, new_vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.clone.post.assert_called_once_with(
        newid=9100
    )


def test_set_description_calls_config(client, fake_api):
    client.set_description(vmid=9100, description="job_id=42 started_at=now")
    fake_api.nodes.return_value.lxc.return_value.config.put.assert_called_once_with(
        description="job_id=42 started_at=now"
    )


def test_get_description_returns_string(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "description": "job_id=42 started_at=2026-04-26T00:00:00",
        "hostname": "CT9100",
    }
    assert client.get_description(vmid=9100) == "job_id=42 started_at=2026-04-26T00:00:00"


def test_start_calls_api(client, fake_api):
    client.start(vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.status.start.post.assert_called_once()


def test_stop_calls_api(client, fake_api):
    client.stop(vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.status.stop.post.assert_called_once()


def test_destroy_calls_api(client, fake_api):
    client.destroy(vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.delete.assert_called_once()
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_proxmox.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/proxmox.py`**

```python
from typing import Iterable


class ProxmoxClient:
    def __init__(self, *, api, node: str):
        self._api = api
        self._node = node

    def _node_lxc(self):
        return self._api.nodes(self._node).lxc

    def _lxc(self, vmid: int):
        return self._api.nodes(self._node).lxc(str(vmid))

    def list_lxcs_in_range(self, *, start: int, end: int) -> list[int]:
        all_lxcs = self._node_lxc().get()
        return [
            int(c["vmid"])
            for c in all_lxcs
            if start <= int(c["vmid"]) <= end
        ]

    def allocate_vmid(self, *, start: int, end: int) -> int:
        used = set(self.list_lxcs_in_range(start=start, end=end))
        for v in range(start, end + 1):
            if v not in used:
                return v
        raise RuntimeError(f"no free VMID in range {start}-{end}")

    def clone(self, *, template_vmid: int, new_vmid: int) -> None:
        self._lxc(template_vmid).clone.post(newid=new_vmid)

    def set_description(self, *, vmid: int, description: str) -> None:
        self._lxc(vmid).config.put(description=description)

    def get_description(self, *, vmid: int) -> str:
        cfg = self._lxc(vmid).config.get()
        return cfg.get("description", "")

    def start(self, *, vmid: int) -> None:
        self._lxc(vmid).status.start.post()

    def stop(self, *, vmid: int) -> None:
        self._lxc(vmid).status.stop.post()

    def destroy(self, *, vmid: int) -> None:
        self._lxc(vmid).delete()
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_proxmox.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/proxmox.py controller/tests/test_proxmox.py
git commit -m "feat(controller): add proxmox basic operations"
```

---

## Task 8: Proxmox module — exec, wait_until_ready, status, create-time

**Files:**
- Modify: `controller/src/controller/proxmox.py`
- Modify: `controller/tests/test_proxmox.py`

This task uses the spike outcome from Task 1. If REST exec is available, implement against proxmoxer. Otherwise, the SSH fallback path. Both expose the same `exec(vmid, cmd) -> (stdout, exit_code)` interface.

- [ ] **Step 1: Add the failing tests**

Append to `controller/tests/test_proxmox.py`:
```python
def test_get_status(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "running"
    }
    assert client.get_status(vmid=9100) == "running"


def test_get_create_time_parses_uptime_or_config(client, fake_api):
    """Create time can be inferred from config 'creation_time' if Proxmox exposes it,
    or computed from current time minus uptime as a fallback. Test the helper either way."""
    fake_api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "description": "job_id=42 started_at=2026-04-26T10:00:00+00:00",
    }
    ts = client.get_create_time(vmid=9100)
    assert ts.year == 2026 and ts.month == 4 and ts.day == 26


def test_wait_until_ready_polls_status(client, fake_api, monkeypatch):
    statuses = iter([{"status": "stopped"}, {"status": "running"}])
    fake_api.nodes.return_value.lxc.return_value.status.current.get.side_effect = (
        lambda: next(statuses)
    )
    sleeps = []
    monkeypatch.setattr("controller.proxmox.time.sleep", lambda s: sleeps.append(s))
    client.wait_until_ready(vmid=9100, timeout=5.0, interval=0.1)
    assert len(sleeps) >= 1


def test_wait_until_ready_times_out(client, fake_api, monkeypatch):
    fake_api.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "stopped"
    }
    monkeypatch.setattr("controller.proxmox.time.sleep", lambda s: None)
    with pytest.raises(TimeoutError):
        client.wait_until_ready(vmid=9100, timeout=0.5, interval=0.1)


def test_exec_returns_stdout(client, fake_api):
    """Test depends on Task 1 spike outcome. This test asserts the REST-style happy path."""
    fake_api.nodes.return_value.lxc.return_value.status.exec.post.return_value = {
        "out-data": "JITCONFIG written\n",
        "exitcode": 0,
    }
    out, code = client.exec(vmid=9100, cmd=["sh", "-c", "echo hi"])
    assert "written" in out
    assert code == 0


def test_exec_raises_on_nonzero(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.status.exec.post.return_value = {
        "out-data": "boom\n",
        "exitcode": 1,
    }
    with pytest.raises(RuntimeError, match="exit_code=1"):
        client.exec(vmid=9100, cmd=["false"])
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_proxmox.py -v -k "ready or exec or status or create_time"`
Expected: AttributeError or AssertionError on the new methods.

- [ ] **Step 3: Add the methods to `controller/src/controller/proxmox.py`**

Append to the `ProxmoxClient` class:
```python
import re
import time
from datetime import datetime


_DESC_TS_RE = re.compile(r"started_at=(\S+)")


class ProxmoxClient:
    # ... existing methods above ...

    def get_status(self, *, vmid: int) -> str:
        return self._lxc(vmid).status.current.get()["status"]

    def get_create_time(self, *, vmid: int) -> datetime:
        """Parse the started_at stamp we wrote into the description at clone time."""
        desc = self.get_description(vmid=vmid)
        m = _DESC_TS_RE.search(desc)
        if not m:
            raise ValueError(f"vmid {vmid} description missing started_at")
        return datetime.fromisoformat(m.group(1))

    def wait_until_ready(
        self, *, vmid: int, timeout: float = 30.0, interval: float = 1.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_status(vmid=vmid) == "running":
                time.sleep(interval)  # small grace before first exec
                return
            time.sleep(interval)
        raise TimeoutError(f"vmid {vmid} did not become running within {timeout}s")

    def exec(self, *, vmid: int, cmd: list[str]) -> tuple[str, int]:
        """Run `cmd` inside the LXC. Implementation depends on Task 1 spike.

        REST path (proxmoxer LXC exec):
            result = self._lxc(vmid).status.exec.post(command=cmd)
            return result.get('out-data', ''), int(result.get('exitcode', 0))

        SSH fallback (only if spike found REST exec absent):
            See spike-notes.md and controller.exec_ssh module.
        """
        result = self._lxc(vmid).status.exec.post(command=cmd)
        out = result.get("out-data", "")
        code = int(result.get("exitcode", 0))
        if code != 0:
            raise RuntimeError(f"exec failed: exit_code={code} out={out!r}")
        return out, code
```

If the spike found REST exec absent, replace the body of `exec()` with a call to a new `exec_ssh.run()` helper module (paramiko-based, key path from config). Tests above use the REST shape; if going SSH, mirror the test fixture to paramiko's SSHClient.

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_proxmox.py -v`
Expected: all pass (15 total).

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/proxmox.py controller/tests/test_proxmox.py
git commit -m "feat(controller): add proxmox exec, wait_until_ready, status helpers"
```

---

## Task 9: Webhook handler

**Files:**
- Create: `controller/src/controller/webhook.py`
- Create: `controller/tests/test_webhook.py`

The handler is intentionally minimal: verify, parse, INSERT/UPDATE, return 200. No Proxmox or GitHub calls.

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_webhook.py`:
```python
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from controller import db
from controller.webhook import build_router


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


@pytest.fixture
def app_and_conn(env_overrides):
    import sqlite3

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)

    app = FastAPI()
    app.include_router(
        build_router(
            conn=conn, secret="test-secret", runner_labels=["self-hosted", "lxc"]
        )
    )
    return app, conn


@pytest.fixture
async def client(app_and_conn):
    app, _ = app_and_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _post(client, body: dict, *, action: str, event: str = "workflow_job"):
    raw = json.dumps(body).encode()
    return await client.post(
        "/webhook/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": _sign("test-secret", raw),
            "X-GitHub-Event": event,
        },
    )


async def test_invalid_signature_returns_401(client):
    r = await client.post(
        "/webhook/github",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "workflow_job"},
    )
    assert r.status_code == 401


async def test_unknown_event_type_returns_200(app_and_conn, client):
    r = await _post(client, {}, action="anything", event="push")
    assert r.status_code == 200


async def test_queued_inserts_pending_row(app_and_conn, client):
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 12345, "labels": ["self-hosted", "lxc"]},
    }
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    row = conn.execute("SELECT * FROM runners WHERE job_id=12345").fetchone()
    assert row["state"] == "pending"


async def test_duplicate_queued_is_ignored(app_and_conn, client):
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 1, "labels": ["self-hosted", "lxc"]},
    }
    await _post(client, body, action="queued")
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    rows = conn.execute("SELECT * FROM runners WHERE job_id=1").fetchall()
    assert len(rows) == 1


async def test_in_progress_updates_state(app_and_conn, client):
    _, conn = app_and_conn
    queued = {
        "action": "queued",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
    }
    await _post(client, queued, action="queued")
    in_prog = {
        "action": "in_progress",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
    }
    await _post(client, in_prog, action="in_progress")
    row = conn.execute("SELECT * FROM runners WHERE job_id=7").fetchone()
    assert row["state"] == "running"


async def test_completed_updates_state(app_and_conn, client):
    _, conn = app_and_conn
    queued = {
        "action": "queued",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
    }
    await _post(client, queued, action="queued")
    done = {
        "action": "completed",
        "workflow_job": {"id": 7, "labels": ["self-hosted", "lxc"]},
    }
    await _post(client, done, action="completed")
    row = conn.execute("SELECT * FROM runners WHERE job_id=7").fetchone()
    assert row["state"] == "completed"


async def test_label_mismatch_is_ignored(app_and_conn, client):
    _, conn = app_and_conn
    body = {
        "action": "queued",
        "workflow_job": {"id": 99, "labels": ["self-hosted", "windows"]},
    }
    r = await _post(client, body, action="queued")
    assert r.status_code == 200
    assert conn.execute("SELECT * FROM runners WHERE job_id=99").fetchone() is None
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_webhook.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/webhook.py`**

```python
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
        if not labels.issubset(label_set):
            return {"ok": True, "ignored": "labels"}
        if not job_id or not action:
            return {"ok": True, "ignored": "missing fields"}
        if action == "queued":
            inserted = db.insert_pending_runner(conn, job_id=job_id)
            db.audit(conn, event="webhook_queued", job_id=job_id, detail="duplicate" if inserted is None else None)
        elif action == "in_progress":
            db.update_state_by_job_id(conn, job_id=job_id, new_state="running")
            db.audit(conn, event="webhook_in_progress", job_id=job_id)
        elif action == "completed":
            db.update_state_by_job_id(conn, job_id=job_id, new_state="completed")
            db.audit(conn, event="webhook_completed", job_id=job_id)
        return {"ok": True}

    return router
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_webhook.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/webhook.py controller/tests/test_webhook.py
git commit -m "feat(controller): add webhook handler"
```

---

## Task 10: Worker — spawn pass

**Files:**
- Create: `controller/src/controller/worker.py`
- Create: `controller/tests/test_worker.py`

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_worker.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_worker.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/worker.py` (spawn pass only)**

```python
import logging
import sqlite3
from datetime import datetime, timezone

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


async def _spawn_one(
    *, conn, proxmox, github, row, template_vmid, vmid_range, runner_labels
):
    runner_id = row["id"]
    job_id = row["job_id"]
    db.update_state_by_id(conn, runner_id=runner_id, new_state="spawning")
    db.audit(conn, event="spawn_started", job_id=job_id)
    vmid: int | None = None
    try:
        jit = await github.generate_jit_config(
            name=f"runner-{job_id}", labels=runner_labels
        )
        vmid = proxmox.allocate_vmid(start=vmid_range[0], end=vmid_range[1])
        proxmox.clone(template_vmid=template_vmid, new_vmid=vmid)
        now_iso = datetime.now(timezone.utc).isoformat()
        proxmox.set_description(
            vmid=vmid, description=f"job_id={job_id} started_at={now_iso}"
        )
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
        db.audit(
            conn, event="spawn_failed", job_id=job_id, vmid=vmid, detail=str(e)
        )


async def cleanup_pass(*, conn, proxmox) -> None:
    """Implemented in Task 11."""
    pass
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_worker.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/worker.py controller/tests/test_worker.py
git commit -m "feat(controller): add worker spawn pass"
```

---

## Task 11: Worker — cleanup pass

**Files:**
- Modify: `controller/src/controller/worker.py`
- Modify: `controller/tests/test_worker.py`

- [ ] **Step 1: Add the failing tests**

Append to `controller/tests/test_worker.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_worker.py -v -k cleanup`
Expected: AssertionError (cleanup_pass is currently a no-op).

- [ ] **Step 3: Replace the cleanup_pass body in `controller/src/controller/worker.py`**

```python
from datetime import datetime, timezone


async def cleanup_pass(*, conn, proxmox) -> None:
    rows = db.select_by_state(conn, "completed")
    for row in rows:
        runner_id = row["id"]
        vmid = row["vmid"]
        job_id = row["job_id"]
        try:
            if vmid is not None:
                proxmox.stop(vmid=vmid)
                proxmox.destroy(vmid=vmid)
            db.update_state_by_id(
                conn,
                runner_id=runner_id,
                new_state="cleaned",
                cleaned_at=datetime.now(timezone.utc),
            )
            db.audit(conn, event="cleanup_succeeded", job_id=job_id, vmid=vmid)
        except Exception as e:
            log.exception("cleanup failed for job_id=%s vmid=%s", job_id, vmid)
            db.update_state_by_id(
                conn, runner_id=runner_id, new_state="failed", last_error=str(e)
            )
            db.audit(
                conn, event="cleanup_failed", job_id=job_id, vmid=vmid, detail=str(e)
            )
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_worker.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/worker.py controller/tests/test_worker.py
git commit -m "feat(controller): add worker cleanup pass"
```

---

## Task 12: Worker — orchestration loop

**Files:**
- Modify: `controller/src/controller/worker.py`
- Modify: `controller/tests/test_worker.py`

- [ ] **Step 1: Add the failing test**

Append to `controller/tests/test_worker.py`:
```python
import asyncio


async def test_run_loop_calls_passes_then_sleeps(conn, proxmox, github_client, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("controller.worker.asyncio.sleep", fake_sleep)

    from controller.worker import run

    with pytest.raises(asyncio.CancelledError):
        await run(
            conn=conn, proxmox=proxmox, github=github_client,
            cap=3, template_vmid=9000, vmid_range=(9100, 9199),
            runner_labels=["self-hosted", "lxc"], interval=2.0,
        )

    assert sleeps == [2.0, 2.0]
```

- [ ] **Step 2: Run test to confirm failure**

Run: `cd controller && pytest tests/test_worker.py::test_run_loop_calls_passes_then_sleeps -v`
Expected: ImportError for `run`.

- [ ] **Step 3: Add `run` to `controller/src/controller/worker.py`**

```python
import asyncio


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
                conn=conn, proxmox=proxmox, github=github,
                cap=cap, template_vmid=template_vmid, vmid_range=vmid_range,
                runner_labels=runner_labels,
            )
            await cleanup_pass(conn=conn, proxmox=proxmox)
        except Exception:
            log.exception("worker tick failed")
        await asyncio.sleep(interval)
```

- [ ] **Step 4: Run test to confirm pass**

Run: `cd controller && pytest tests/test_worker.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/worker.py controller/tests/test_worker.py
git commit -m "feat(controller): add worker orchestration loop"
```

---

## Task 13: Reconciler — adoption + ghost reaping

**Files:**
- Create: `controller/src/controller/reconciler.py`
- Create: `controller/tests/test_reconciler.py`

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_reconciler.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_reconciler.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/reconciler.py`**

```python
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


def _parse_job_id(description: str) -> int | None:
    for tok in description.split():
        if tok.startswith("job_id="):
            try:
                return int(tok[len("job_id="):])
            except ValueError:
                return None
    return None
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_reconciler.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/reconciler.py controller/tests/test_reconciler.py
git commit -m "feat(controller): add reconciler adoption + ghost reaping"
```

---

## Task 14: Reconciler — timeouts + missed-completed polling

**Files:**
- Modify: `controller/src/controller/reconciler.py`
- Modify: `controller/tests/test_reconciler.py`

- [ ] **Step 1: Add the failing tests**

Append to `controller/tests/test_reconciler.py`:
```python
async def test_reaps_timed_out_running_lxc(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=1)
    db.update_state_by_id(conn, runner_id=1, new_state="running", vmid=9100)
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    conn.execute("UPDATE runners SET started_at=? WHERE id=1", (long_ago,))
    proxmox.list_lxcs_in_range.return_value = [9100]
    proxmox.get_create_time.return_value = datetime.fromisoformat(long_ago)
    proxmox.get_description.return_value = f"job_id=1 started_at={long_ago}"

    await reconcile_once(
        conn=conn, proxmox=proxmox, github=github_client,
        vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
    )

    proxmox.stop.assert_called_with(vmid=9100)
    proxmox.destroy.assert_called_with(vmid=9100)
    row = conn.execute("SELECT * FROM runners WHERE job_id=1").fetchone()
    assert row["state"] == "failed"
    assert row["last_error"] == "timeout"


async def test_polls_github_and_marks_completed(conn, proxmox, github_client):
    db.insert_pending_runner(conn, job_id=1)
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    db.update_state_by_id(conn, runner_id=1, new_state="running", vmid=9100)
    conn.execute("UPDATE runners SET started_at=? WHERE id=1", (old,))
    proxmox.list_lxcs_in_range.return_value = [9100]
    proxmox.get_create_time.return_value = datetime.fromisoformat(old)
    proxmox.get_description.return_value = f"job_id=1 started_at={old}"
    github_client.get_workflow_job = AsyncMock(
        return_value={"status": "completed", "conclusion": "success", "repository": {"full_name": "myorg/repo"}}
    )

    await reconcile_once(
        conn=conn, proxmox=proxmox, github=github_client,
        vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
    )

    row = conn.execute("SELECT * FROM runners WHERE job_id=1").fetchone()
    assert row["state"] == "completed"
```

Note: The github_client polling path requires knowing which repo the job belongs to. Since we don't store repo, we'll thread the org and search across recent workflow runs, or skip polling if the GitHub job lookup endpoint requires repo context. For simplicity in this plan we add a `repo` column later if needed; for now the polling step calls `github.get_workflow_job(job_id=...)` and that helper should handle the lookup. Update `GitHubClient.get_workflow_job` accordingly in this task.

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_reconciler.py -v -k "timed_out or polls"`
Expected: AssertionError or AttributeError.

- [ ] **Step 3: Wire `repo` into the webhook handler**

The `repo` column already exists from Task 4. The webhook just needs to pass it through.

Edit `controller/src/controller/webhook.py` — in the `"queued"` branch, change:

```python
        if action == "queued":
            inserted = db.insert_pending_runner(conn, job_id=job_id)
```

to:

```python
        if action == "queued":
            repo = (payload.get("repository") or {}).get("full_name")
            inserted = db.insert_pending_runner(conn, job_id=job_id, repo=repo)
```

Update `tests/test_webhook.py` so `_post` payloads include `"repository": {"full_name": "myorg/repo"}`. Add one assertion in `test_queued_inserts_pending_row`:

```python
    assert row["repo"] == "myorg/repo"
```

- [ ] **Step 4: Implement timeout + polling in `controller/src/controller/reconciler.py`**

Add to `reconcile_once` after the ghost-reap block:

```python
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
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `cd controller && pytest tests/ -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add controller/src/controller/db.py controller/src/controller/webhook.py controller/src/controller/reconciler.py controller/tests/
git commit -m "feat(controller): add reconciler timeouts + github polling"
```

---

## Task 15: Reconciler — orchestration loop

**Files:**
- Modify: `controller/src/controller/reconciler.py`
- Modify: `controller/tests/test_reconciler.py`

- [ ] **Step 1: Add the failing test**

Append to `controller/tests/test_reconciler.py`:
```python
import asyncio


async def test_reconciler_run_calls_reconcile_then_sleeps(conn, proxmox, github_client, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("controller.reconciler.asyncio.sleep", fake_sleep)
    proxmox.list_lxcs_in_range.return_value = []

    from controller.reconciler import run

    with pytest.raises(asyncio.CancelledError):
        await run(
            conn=conn, proxmox=proxmox, github=github_client,
            vmid_range=(9100, 9199), max_job_duration=timedelta(hours=6),
            interval=300.0,
        )

    assert sleeps == [300.0, 300.0]
```

- [ ] **Step 2: Run test to confirm failure**

Run: `cd controller && pytest tests/test_reconciler.py::test_reconciler_run_calls_reconcile_then_sleeps -v`
Expected: ImportError for `run`.

- [ ] **Step 3: Add `run` to `controller/src/controller/reconciler.py`**

```python
import asyncio


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
```

- [ ] **Step 4: Run test to confirm pass**

Run: `cd controller && pytest tests/test_reconciler.py -v`
Expected: all reconciler tests pass.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/reconciler.py controller/tests/test_reconciler.py
git commit -m "feat(controller): add reconciler orchestration loop"
```

---

## Task 16: Main app — FastAPI assembly + /health + /audit

**Files:**
- Create: `controller/src/controller/main.py`
- Create: `controller/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

`controller/tests/test_main.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(env_overrides, monkeypatch):
    """Build the real app but override Proxmox + GitHub with fakes."""
    from unittest.mock import AsyncMock, MagicMock

    fake_proxmox = MagicMock()
    fake_proxmox.list_lxcs_in_range.return_value = []
    fake_github = MagicMock()
    fake_github.generate_jit_config = AsyncMock(return_value="JITSTRING")
    fake_github.get_workflow_job = AsyncMock(return_value={"status": "in_progress"})

    monkeypatch.setattr("controller.main._build_proxmox", lambda settings: fake_proxmox)
    monkeypatch.setattr("controller.main._build_github", lambda settings: fake_github)

    from controller.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_health_returns_state_counts(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert "states" in r.json()


async def test_audit_endpoint_returns_list(client):
    r = await client.get("/audit")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `cd controller && pytest tests/test_main.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `controller/src/controller/main.py`**

```python
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
    api = ProxmoxAPI(
        settings.proxmox_url.replace("https://", "").replace("http://", ""),
        token_name=settings.proxmox_token_id.split("!", 1)[1],
        user=settings.proxmox_token_id.split("!", 1)[0],
        token_value=settings.proxmox_token_secret,
        verify_ssl=False,
        service="PVE",
    )
    return ProxmoxClient(api=api, node=settings.proxmox_node)


def _build_github(settings: Settings) -> GitHubClient:
    return GitHubClient(pat=settings.github_pat, org=settings.github_org)


_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    logging.basicConfig(level=settings.log_level)

    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    proxmox = _build_proxmox(settings)
    github = _build_github(settings)

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
            conn=conn, proxmox=proxmox, github=github,
            cap=settings.max_concurrent_runners,
            template_vmid=settings.template_vmid,
            vmid_range=(settings.runner_vmid_range_start, settings.runner_vmid_range_end),
            runner_labels=settings.runner_labels,
        )
    )
    reconciler_task = asyncio.create_task(
        reconciler.run(
            conn=conn, proxmox=proxmox, github=github,
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
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `cd controller && pytest tests/test_main.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add controller/src/controller/main.py controller/tests/test_main.py
git commit -m "feat(controller): assemble fastapi app, lifespan, /health, /audit"
```

---

## Task 17: End-to-end test

**Files:**
- Create: `controller/tests/test_e2e.py`

One test that drives the full lifecycle: queued webhook → worker spawns → in_progress webhook → completed webhook → worker cleans up.

- [ ] **Step 1: Write the test**

`controller/tests/test_e2e.py`:
```python
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
```

- [ ] **Step 2: Run the test**

Run: `cd controller && pytest tests/test_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Run the full test suite to confirm nothing else broke**

Run: `cd controller && pytest -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add controller/tests/test_e2e.py
git commit -m "test(controller): add end-to-end lifecycle test"
```

---

## Task 18: README, smoke test docs, and clean up the spike note

**Files:**
- Create: `controller/README.md`
- Delete: `controller/spike-notes.md`

- [ ] **Step 1: Write `controller/README.md`**

```markdown
# Controller

Single Python service that turns GitHub `workflow_job` webhooks into ephemeral LXC runners on Proxmox and reaps them when jobs finish.

## Run

```bash
cp .env.example .env  # edit with your values
docker compose up --build -d
docker compose logs -f
```

Webhook URL: `https://<host>:8000/webhook/github`
Health: `GET /health`
Audit: `GET /audit?job_id=<id>&limit=100`

## Required template (PRD 1)

The LXC at `TEMPLATE_VMID` must:
- Have `actions/runner` installed at a known path.
- Have a systemd unit `gha-runner.service` with `EnvironmentFile=/etc/runner.env` that runs `Runner.Listener run --jitconfig "$JITCONFIG"`.
- Have that unit **disabled** (controller starts it explicitly after writing the env file).
- Have network reach to `api.github.com`.

## Configuration

See `.env.example`.

## Tests

```bash
uv pip install --system -e ".[dev]"
pytest -v
```

## Manual smoke test

1. Configure `.env` with a real PAT, webhook secret, and Proxmox token.
2. `docker compose up -d`.
3. In a private GitHub repo in your org, add a workflow:
   ```yaml
   jobs:
     test:
       runs-on: [self-hosted, lxc]
       steps:
         - run: echo hello
   ```
4. Push. Watch `docker compose logs -f`.
5. Confirm an LXC was cloned, the workflow ran, and the LXC was destroyed (`pct list` on the host).
6. Hit `GET /audit?job_id=<id>` to inspect the trail.

## Architecture

See `docs/superpowers/specs/2026-04-26-controller-service-design.md`.
```

- [ ] **Step 2: Delete the spike notes**

```bash
git rm controller/spike-notes.md
```

- [ ] **Step 3: Commit**

```bash
git add controller/README.md
git commit -m "docs(controller): add readme + remove spike notes"
```

---

## Done when

- All tasks above are complete and committed.
- `pytest -v` passes in `controller/`.
- `docker compose up --build` produces a running container that responds 200 to `GET /health`.
- Manual smoke test (Task 18 step 4 sub-instructions) shows: webhook arrives → LXC clones → job runs → LXC destroys.
