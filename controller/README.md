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

## SSH to Proxmox host

`pct exec` is not exposed via the Proxmox REST API (see commit history for the spike notes), so the controller SSHes from inside its container to the Proxmox host and runs `pct exec` there. Requirements:

- An SSH private key mounted at `/etc/controller/proxmox_ssh_key` (mode 600).
- The corresponding public key authorized for `root@<PROXMOX_HOST>` (or for a user with `pct exec` permission — typically PVEAdmin role + Sys.Console privilege).
- `PROXMOX_HOST` env var pointing at the Proxmox node hostname or IP.

## Configuration

See `.env.example`.

## Tests

```bash
uv pip install --system -e ".[dev]"
pytest -v
```

## Manual smoke test

1. Configure `.env` with a real PAT, webhook secret, Proxmox token, and SSH key.
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
