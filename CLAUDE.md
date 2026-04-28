# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

Monorepo with two independently deployable units that share a single contract:

- **`controller/`** — Python 3.12 / FastAPI service, deployed via Docker. Reacts to GitHub `workflow_job` webhooks and manages ephemeral LXC runner lifecycle on a Proxmox host.
- **`template-builder/`** — Bash script run *on the Proxmox node itself* (not in the controller container) to build the runner LXC template.

The contract: the template at `TEMPLATE_VMID` must contain `actions/runner` plus a **disabled** `gha-runner.service` systemd unit with `EnvironmentFile=/etc/runner.env`. The controller clones it, writes `JITCONFIG=…` into that env file, then starts the unit. Changing one side without the other breaks the system.

Specs and plans live under `docs/superpowers/`. Commit style is conventional commits (`feat:`, `fix:`).

## Common commands

All controller commands are run from `controller/`:

```bash
uv sync --extra dev               # install deps
uv run pytest -v                  # full test suite
uv run pytest tests/test_worker.py::test_name -v   # single test
uv run ruff check                 # lint
uv run ruff format --check        # format check (CI runs this)
uv run ruff format                # apply formatting
docker compose up --build -d      # local run (needs .env)
```

Template-builder is bash; verify locally before pushing:

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

End-to-end testing for template-builder requires a real Proxmox node — there are no unit tests for it.

## Controller architecture

Three async loops run concurrently from `main.py`'s lifespan, sharing a single SQLite connection (`/data/controller.sqlite`):

1. **`webhook.py`** — FastAPI router. HMAC-verifies the GitHub signature, filters events, inserts/updates rows.
2. **`worker.py`** — spawn pass (clone template → start → write JIT → start service) + cleanup pass (stop+destroy completed/failed LXCs). Runs every 2s.
3. **`reconciler.py`** — every 5 min: adopt orphan LXCs (in-range VMIDs the DB doesn't know about, age > 5 min), reap ghosts (DB rows whose VMID disappeared), force-kill timed-out runs, and poll GitHub for jobs we missed the `completed` webhook for.

Runner row state machine: `pending → spawning → running → completed → cleaned`, with `failed` reachable from any state. The `cleaned_at` column gates cleanup retries.

`db.py` owns all SQL — keep it that way; the other modules don't import `sqlite3` for queries.

## Non-obvious behavior

- **Label matching is strict subset.** A job is handled only if **every** label in `RUNNER_LABELS` is in `runs-on:`. Bare `runs-on: self-hosted` is *deliberately* ignored so this controller can't hijack other self-hosted pools. (`webhook.py` line ~29)
- **Proxmox `pct exec` is reached over SSH, not the REST API.** The REST API doesn't expose that endpoint, so `ProxmoxClient.exec()` shells out to `ssh root@PROXMOX_HOST -- pct exec ...` using a key mounted at `/etc/controller/proxmox_ssh_key`. The container needs both the Proxmox API token *and* SSH access to the host.
- **Orphan adoption uses LXC description as ground truth.** `worker.py` writes `job_id=… started_at=…` into the LXC description after clone; the reconciler parses it back. Don't rewrite that description elsewhere.
- **Cleanup error handling has a one-shot demotion rule.** A failed cleanup on a `completed` row demotes it to `failed`; a failed cleanup on an already-`failed` row leaves the row alone for the next tick. Preserve this — it prevents log spam on persistently broken VMs while still surfacing the first failure.
- **Template-builder self-installs on first run** to `/usr/local/sbin/build-runner-template.sh` and adds a quarterly cron entry. The script handles being invoked via `curl | bash` (see commit `b409b73`).
- **`RUNNER_VERSION` / `RUNNER_SHA256` in `template-builder/build-runner-template.sh` are pinned** and bumped via PR — see that file's README for the bump procedure.

## Tests

`pytest-asyncio` is in `auto` mode (set in `pyproject.toml`), so async test functions don't need decorators. `respx` mocks GitHub HTTP; Proxmox is mocked at the `ProxmoxClient` boundary in `conftest.py`. There is a `test_e2e.py` that wires the loops together against fakes — useful when changing cross-module flow.

## CI

`.github/workflows/ci.yml` runs ruff + pytest on PR and on push to `main`. On `main`, it also builds and pushes `ghcr.io/<repo>/controller:latest` and `:sha-<short>`.
