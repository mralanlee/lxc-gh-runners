# Template Builder — Design

**Date:** 2026-04-26
**PRD:** 1 of N (template-builder)
**Status:** Approved for planning

## Goal

A bash script that builds a reusable Proxmox LXC template containing the GitHub Actions self-hosted runner, Docker, and the system libraries needed for typical Go / Rust / Node / Playwright jobs. The script runs manually for the first build and self-installs a quarterly cron entry for refreshes.

## Scope

**In scope (this PRD):**
- Single bash script, runs as root on a Proxmox node.
- Builds privileged LXC with nesting + keyctl for Docker-in-LXC.
- Pre-installs Docker, runner binary, system libs for common build/test workloads.
- Installs (but does not enable) a systemd unit for the runner.
- Self-installs a quarterly cron entry on first run.
- Destroys and rebuilds the same fixed `TEMPLATE_VMID` each run.

**Explicitly out of scope:**
- Atomic swap / rollback (rebuild same VMID; if broken, fix and re-run).
- Smoke testing (operator notices when it doesn't work).
- Notifications beyond the default cron mail to root.
- Per-clone JIT config injection (PRD 2: provisioner).
- Cleanup of old runners on GitHub side (PRD 2 territory).

## Architecture

One bash script (`template-builder/build-runner-template.sh`) on a Proxmox host. Top-of-file configuration block; everything else is a sequence of pre-flight checks, container build steps, and finalisation. All container-internal work runs through `pct exec`. The systemd unit and `runner.env` placeholder are emitted via heredoc so the script remains a single self-contained artifact.

## Repo layout

```
template-builder/
  build-runner-template.sh
  README.md                          # operator usage
docs/superpowers/
  specs/2026-04-26-template-builder-design.md
  plans/2026-04-26-template-builder.md
```

## Configuration block (top of script)

```bash
TEMPLATE_VMID="${TEMPLATE_VMID:-9000}"
STORAGE_POOL="${STORAGE_POOL:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
UBUNTU_VERSION="${UBUNTU_VERSION:-24.04}"
RUNNER_VERSION="<pinned at implementation>"   # bump manually
RUNNER_SHA256="<pinned at implementation>"    # bump alongside
INSTALL_PATH="/usr/local/sbin/build-runner-template.sh"
CRON_PATH="/etc/cron.d/build-runner-template"
CRON_SCHEDULE="0 3 1 */3 *"                   # 03:00 on day 1 of Jan/Apr/Jul/Oct
```

Env-var override for `TEMPLATE_VMID`, `STORAGE_POOL`, `BRIDGE`, `UBUNTU_VERSION`. Runner version + SHA are baked into the script and bumped via PR.

## Script behaviour (in order)

### 1. Bootstrap

- `set -euo pipefail`
- `ERR` trap that logs `FAILED at line $LINENO` and exits non-zero.
- Timestamped `log()` helper, all output to stdout (cron will mail it).

### 2. Pre-flight checks

- Running as root.
- `pct`, `pveam`, `pvesh` available on `$PATH`.
- `STORAGE_POOL` exists (`pvesm status` contains it).
- `BRIDGE` exists (`/sys/class/net/$BRIDGE` exists).

### 3. Self-install

- If `$0` is not at `INSTALL_PATH`: copy itself there with mode `0755`.
- Write `CRON_PATH` (mode `0644`) containing the schedule line invoking `INSTALL_PATH`. Idempotent — overwrites every run.

### 4. Ensure Ubuntu base template present

- `pveam update`.
- If `pveam list local` does not contain a matching `ubuntu-${UBUNTU_VERSION}-standard_*_amd64.tar.zst`, run `pveam available | grep ubuntu-${UBUNTU_VERSION}-standard` to find the latest, then `pveam download local <name>`.

### 5. Reset target VMID

- If `pct status $TEMPLATE_VMID` succeeds: `pct stop $TEMPLATE_VMID --skiplock` (ignore failure if already stopped), then `pct destroy $TEMPLATE_VMID --purge --force`.

### 6. Create container

```bash
pct create "$TEMPLATE_VMID" "local:vztmpl/${UBUNTU_TEMPLATE_FILENAME}" \
  --hostname runner-template \
  --storage "$STORAGE_POOL" \
  --rootfs "${STORAGE_POOL}:32" \
  --memory 2048 --cores 2 \
  --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
  --features "nesting=1,keyctl=1" \
  --unprivileged 0 \
  --onboot 0 --start 1
```

### 7. Wait for network

- Poll `pct exec $TEMPLATE_VMID -- getent hosts github.com` every 2s up to 60s. Fail with a clear message on timeout.

### 8. In-container setup (`pct exec` for each block)

**Base packages (system libs only — option A):**

```
curl wget ca-certificates git jq sudo gnupg lsb-release
build-essential pkg-config libssl-dev libyaml-dev
```

**Playwright system libraries** (Chromium + Firefox + WebKit, Ubuntu 24.04):

The full `apt install` list — pinned in the script and refreshed when bumping Playwright support. List sourced from Playwright's own `dependencies.ts` for Ubuntu 24.04 (Chromium + Firefox + WebKit). Includes packages such as `libnss3`, `libatk-bridge2.0-0t64`, `libgbm1`, `libasound2t64`, `libxkbcommon0`, `libgstreamer1.0-0`, `libavif16`, `libwoff1` etc. Implementation plan will inline the exact list.

**Docker** — installed from Docker's official apt repository (more current than the Ubuntu `docker.io` package):

- Add Docker's GPG key + apt source for `${UBUNTU_VERSION}`.
- `apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`.

**Runner user:**

- `useradd -m -s /bin/bash runner`
- `usermod -aG docker runner`
- Write `/etc/sudoers.d/runner` with `runner ALL=(ALL) NOPASSWD:ALL`, mode `0440`, validated with `visudo -c -f /etc/sudoers.d/runner`.

**Runner binary:**

- `mkdir -p /opt/runner && cd /opt/runner`
- `curl -fsSLo runner.tar.gz https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz`
- `echo "${RUNNER_SHA256}  runner.tar.gz" | sha256sum -c -` — fail on mismatch.
- `tar xzf runner.tar.gz && rm runner.tar.gz`
- `chown -R runner:runner /opt/runner`
- `./bin/installdependencies.sh` (runner's own dep installer; idempotent with the libs already installed).

**runner.env placeholder:**

```
JITCONFIG=
```

Path: `/etc/runner.env`, mode `0640`, owner `root:runner`.

**systemd unit** (`/etc/systemd/system/github-runner.service`):

```ini
[Unit]
Description=GitHub Actions Runner
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=runner
WorkingDirectory=/opt/runner
EnvironmentFile=/etc/runner.env
ExecStart=/opt/runner/run.sh --jitconfig ${JITCONFIG}
Restart=on-failure
RestartSec=10
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=5min

[Install]
WantedBy=multi-user.target
```

- `systemctl daemon-reload`.
- **Do not enable.** The provisioner (PRD 2) writes the real `JITCONFIG` to `/etc/runner.env` and then runs `systemctl enable --now github-runner`. This avoids a crash-loop in any clone whose env is not yet populated.

### 9. Finalise

- `pct stop $TEMPLATE_VMID`
- `pct template $TEMPLATE_VMID`
- `log "template $TEMPLATE_VMID built; runner ${RUNNER_VERSION}"`

## Verification

- `bash -n template-builder/build-runner-template.sh` — syntax.
- `shellcheck template-builder/build-runner-template.sh` — lint, must pass with no findings (or explicit `# shellcheck disable` with rationale).
- Operator runs the script on a real Proxmox node, then `pct clone $TEMPLATE_VMID <new>` and confirms a runner registers with a JIT config (manual smoke test, deferred to PRD 2 tooling for repeatability).

## Open questions / future PRDs

- **JIT config injection mechanism.** The template ships an empty `JITCONFIG=` placeholder; the provisioner (PRD 2) is the right place to settle whether injection happens via post-clone `pct exec`, cloud-init, or another path.
- **Toolchain bake vs setup-actions.** This PRD ships system libs only. If `setup-go` / `setup-rust` / `setup-node` per-job downloads turn out to be too slow in practice, a follow-up PRD can add baked-in toolchains.
- **Multi-arch.** amd64 only for now. arm64 support is a future PRD if/when the Proxmox host fleet includes ARM nodes.
