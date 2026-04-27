# template-builder

Bash script that builds a Proxmox LXC template containing the GitHub Actions runner, Docker, and the system libraries needed for typical Go / Rust / Node / Playwright workloads.

## What it does

1. Pre-flight checks (root, `pct`/`pveam`/`pvesm`, storage pool, bridge).
2. Self-installs to `/usr/local/sbin/build-runner-template.sh` and writes a quarterly cron entry to `/etc/cron.d/build-runner-template` (03:00 on day 1 of Jan/Apr/Jul/Oct).
3. Ensures the Ubuntu 24.04 LXC base template is present (downloads via `pveam` if missing).
4. Destroys any container/template at `TEMPLATE_VMID` (default `9000`).
5. Creates a privileged LXC with `nesting=1,keyctl=1`, installs Docker (upstream apt), the pinned `actions/runner` release (SHA256 verified), the `runner` user (docker group + passwordless sudo), system libraries for common build/test workloads (Playwright deps included), and a `github-runner.service` systemd unit.
6. The unit is **installed but not enabled**. A clone-time provisioner (PRD 2) writes the real JIT config to `/etc/runner.env` and enables the service.
7. Stops the container and converts it to a Proxmox template.

## Usage

Copy the script to your Proxmox node and run it as root:

```bash
scp template-builder/build-runner-template.sh root@proxmox:/tmp/
ssh root@proxmox /tmp/build-runner-template.sh
```

The first run installs the script to `/usr/local/sbin/` and the quarterly cron entry. Subsequent manual or cron runs use the installed copy.

## Configuration

Override defaults via environment variables:

| Variable | Default | Notes |
|---|---|---|
| `TEMPLATE_VMID` | `9000` | Fixed; rebuilt in place. |
| `STORAGE_POOL` | `local-lvm` | Must exist on the node. |
| `BRIDGE` | `vmbr0` | Must exist on the node. |
| `UBUNTU_VERSION` | `24.04` | Auto-downloads via `pveam` if missing. |

`RUNNER_VERSION` and `RUNNER_SHA256` are pinned at the top of the script and bumped via PR.

## Bumping the runner version

1. Open https://github.com/actions/runner/releases/latest.
2. Find the `actions-runner-linux-x64-<version>.tar.gz` line in the SHA-256 Checksums section of the release notes.
3. Update `RUNNER_VERSION` and `RUNNER_SHA256` at the top of `build-runner-template.sh`.
4. PR + commit. Next cron tick (or a manual run) picks it up.

## Verification

Locally before pushing:

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

End-to-end is tested by running the script on a real Proxmox node, then `pct clone $TEMPLATE_VMID <new-vmid>` and confirming the runner registers (the latter requires PRD 2's provisioner).
