# Spike: Proxmox LXC exec

- **REST endpoint exists:** no
- **proxmoxer support:** no
- **Decision:** SSH
- **Implementation note for proxmox.exec():** see below

## Evidence

### No REST endpoint for LXC exec

The Proxmox VE REST API has no `/nodes/{node}/lxc/{vmid}/exec` (or equivalent) endpoint.
Evidence:

1. **Proxmox bugzilla #4623** — "Implement API call to execute commands in a LXC container" — status: **NEW** (filed 2023-11-21, still open as of April 2026). A Proxmox developer (Fabian Grünbichler) confirmed the feature does not exist but noted it is theoretically feasible in the future. Source: https://bugzilla.proxmox.com/show_bug.cgi?id=4623

2. **QEMU analogue exists; LXC analogue does not.** The API has `POST /nodes/{node}/qemu/{vmid}/agent/exec` (requires QEMU guest agent inside the VM). No parallel endpoint exists under `/nodes/{node}/lxc/{vmid}/`.

3. **proxmoxer 2.3.0 source confirms QEMU-only.** The library contains explicit special-casing for `agent/exec` in two places, both scoped to QEMU:
   - [`proxmoxer/backends/https.py:219`](https://github.com/proxmoxer/proxmoxer/blob/2.3.0/proxmoxer/backends/https.py#L219) — `if k == "command" and url.endswith("agent/exec"):`
   - [`proxmoxer/backends/command_base.py:69`](https://github.com/proxmoxer/proxmoxer/blob/2.3.0/proxmoxer/backends/command_base.py#L69) — `if "/agent/exec" in url:`
   
   There is no analogous code path for LXC exec. proxmoxer is a thin dynamic wrapper over the PVE REST API (see `core.py` — `ProxmoxResource.__getattr__` builds URL segments dynamically); absence of special handling means the endpoint simply does not exist in the API.

   proxmoxer 2.3.0 on PyPI: https://pypi.org/project/proxmoxer/2.3.0/

### Fallback: SSH → `pct exec`

The only supported mechanism is SSH from the controller container to the Proxmox host, then running `pct exec <vmid> -- <cmd>`.

## Implementation note for proxmox.exec()

```python
# controller/src/controller/proxmox.py

import subprocess
from controller.config import settings  # pydantic-settings; see controller/config.py

# NOTE ON SIGNATURE: the design spec planned proxmox.exec() -> tuple[str, int]
# (stdout, exit_code).  This stub widens it to tuple[str, str, int]
# (stdout, stderr, exit_code) because SSH-via-subprocess gives stderr cheaply
# and the worker writes it into `last_error` on failure.  The Task 8
# implementer should keep the three-tuple.

def exec(vmid: int, cmd: list[str]) -> tuple[str, str, int]:
    """
    Execute a command inside LXC <vmid> via SSH to the Proxmox host.

    Returns (stdout, stderr, exit_code).

    cmd must be a list[str] — this avoids shell-injection; do not concatenate
    user input into a single string.

    Environment requirements:
      - PROXMOX_HOST env var: hostname/IP of the Proxmox node (read via
        controller.config.Settings; added to controller/config.py via
        pydantic-settings — see deployment requirements below).
      - SSH key mounted at /etc/controller/proxmox_ssh_key (chmod 600).
      - The key must be authorized on the Proxmox host for a user that can run
        `pct exec` (typically root, or a user with the PVEAdmin role and
        Sys.Console privilege on the container).
    """
    ssh_key = "/etc/controller/proxmox_ssh_key"
    proxmox_host = settings.proxmox_host  # added to controller/config.py via pydantic-settings; env var: PROXMOX_HOST
    pct_cmd = ["pct", "exec", str(vmid), "--"] + cmd

    ssh_args = [
        "ssh",
        "-i", ssh_key,
        "-o", "StrictHostKeyChecking=accept-new",  # production hardening: mount a pre-populated known_hosts and pass -o UserKnownHostsFile=/etc/controller/known_hosts instead
        "-o", "BatchMode=yes",
        f"root@{proxmox_host}",
        "--",
        *pct_cmd,
    ]
    result = subprocess.run(ssh_args, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode
```

Key points for Task 8:

- **No extra Python dep needed for the basic path.** stdlib `subprocess` calling `ssh` is sufficient. Add `paramiko` only if interactive TTY or streaming output is required (it is not for this use case — we just write a file and start a service).
- **SSH key path:** `/etc/controller/proxmox_ssh_key` (mount via Docker secret or volume; `chmod 600` must be enforced at container start or in the Dockerfile).
- **Proxmox user:** `root@pam` is simplest. A restricted API token cannot substitute here because this is SSH, not the REST API. Alternatively create a dedicated PVE user with the `PVEAdmin` role and ensure `Sys.Console` privilege is granted on the container resource pool.
- **`StrictHostKeyChecking=accept-new`** avoids first-connect prompt in automation while still protecting against MITM on subsequent calls. Production hardening: mount a pre-populated `known_hosts` and pass `-o UserKnownHostsFile=/etc/controller/known_hosts` instead of `accept-new`.
- **`pct exec` exit code propagation:** `subprocess.run` captures the SSH exit code, which mirrors `pct exec`'s exit code when SSH itself succeeds.
- **Retry logic** (per design spec §proxmox.exec first-call timeout): wrap the call in a retry-once-after-2s at the call site in `worker.py`, not inside `proxmox.exec()` itself.

## Deployment requirements

The following must be in place before `proxmox.exec()` can run:

| Requirement | Owner task |
|---|---|
| `PROXMOX_HOST` env var — hostname/IP of the Proxmox node; added to `controller.config.Settings` via pydantic-settings | Task 2 (bootstrap) + Task 3 (config) |
| SSH private key at `/etc/controller/proxmox_ssh_key` (mode 600), authorized on the Proxmox host | Task 2 (bootstrap) |
| Proxmox host user with `pct exec` permission (`root@pam` or PVEAdmin + Sys.Console) | Task 2 (bootstrap) |

## What was NOT needed

- `paramiko` is not required; stdlib `ssh` is sufficient.
- No proxmoxer call for exec at all — proxmoxer is still used for all other operations (clone, start, stop, destroy, list, set_description) where REST endpoints do exist.
