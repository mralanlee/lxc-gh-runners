# Template Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single bash script that produces a Proxmox LXC template containing Docker + the GitHub Actions runner + system libraries for typical Go/Rust/Node/Playwright workloads, and self-installs a quarterly cron entry.

**Architecture:** One bash script (`template-builder/build-runner-template.sh`) on the Proxmox host. Runs as root. Top-of-file configuration block, ERR trap, `log()` and `in_container()` helpers, then a sequence of one-purpose functions called from `main()`. All in-container work goes through `pct exec ... -- bash -c "$(cat <<'EOF' ... EOF)"`. The systemd unit and `runner.env` placeholder are emitted as heredocs.

**Tech Stack:** Bash, Proxmox VE (`pct`, `pveam`, `pvesm`), Ubuntu 24.04 LXC, Docker (upstream apt), GitHub Actions runner.

**Reference spec:** `docs/superpowers/specs/2026-04-26-template-builder-design.md`

**Per-task verification (used in every task):**
- `bash -n template-builder/build-runner-template.sh` — must succeed
- `shellcheck template-builder/build-runner-template.sh` — must exit 0 with no findings (any `# shellcheck disable=...` must be accompanied by a one-line rationale comment)

If `shellcheck` is not installed locally: `brew install shellcheck` (macOS) or `apt install shellcheck` (Linux).

---

## Task 1: Script skeleton — config block + helpers + empty main

**Files:**
- Create: `template-builder/build-runner-template.sh`

- [ ] **Step 1: Create the script with shebang, strict mode, config block, helpers, ERR trap, and an empty `main`**

Path: `template-builder/build-runner-template.sh`

```bash
#!/bin/bash
#
# build-runner-template.sh — Build a Proxmox LXC template with the
# GitHub Actions runner + Docker + common build/test system libraries.
#
# Run as root on a Proxmox node. See template-builder/README.md.
#
set -euo pipefail

# === Configuration ===========================================================

TEMPLATE_VMID="${TEMPLATE_VMID:-9000}"
STORAGE_POOL="${STORAGE_POOL:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
UBUNTU_VERSION="${UBUNTU_VERSION:-24.04}"

# Pinned GitHub Actions runner. Bump both together via PR.
# Latest releases: https://github.com/actions/runner/releases
RUNNER_VERSION="0.0.0"   # set in Task 10
RUNNER_SHA256="0000000000000000000000000000000000000000000000000000000000000000"  # set in Task 10

# Self-install paths
INSTALL_PATH="/usr/local/sbin/build-runner-template.sh"
CRON_PATH="/etc/cron.d/build-runner-template"
CRON_SCHEDULE="0 3 1 */3 *"   # 03:00 on day 1 of Jan/Apr/Jul/Oct

# === Helpers =================================================================

log() {
    printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

on_err() {
    local line=$1
    log "FAILED at line ${line}"
}
trap 'on_err $LINENO' ERR

# Run a multi-line bash snippet inside the template container.
# Usage:
#   in_container "$(cat <<'EOF'
#     set -euo pipefail
#     apt-get update
#   EOF
#   )"
in_container() {
    pct exec "$TEMPLATE_VMID" -- bash -c "$1"
}

# === Steps ===================================================================
# Each step is implemented in its own function and wired into main() below.
# Functions are added by subsequent tasks.

# === Entrypoint ==============================================================

main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    log "no steps wired yet"
}

main "$@"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x template-builder/build-runner-template.sh
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0 with no output.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): script skeleton with config and helpers"
```

---

## Task 2: Pre-flight checks

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `preflight()` function, wire into `main`)

- [ ] **Step 1: Add the `preflight` function above `main`**

Insert this function in the `# === Steps ===` section (before `main`):

```bash
preflight() {
    log "pre-flight checks"

    if [[ $EUID -ne 0 ]]; then
        log "must run as root"
        exit 1
    fi

    local cmd
    for cmd in pct pveam pvesm; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            log "required command not found: ${cmd}"
            exit 1
        fi
    done

    if ! pvesm status | awk 'NR>1 {print $1}' | grep -qx "$STORAGE_POOL"; then
        log "storage pool not found: ${STORAGE_POOL}"
        exit 1
    fi

    if [[ ! -d "/sys/class/net/${BRIDGE}" ]]; then
        log "bridge not found: ${BRIDGE}"
        exit 1
    fi
}
```

- [ ] **Step 2: Wire `preflight` into `main`**

Replace the body of `main` with:

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): add pre-flight checks"
```

---

## Task 3: Self-install (script + cron)

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `self_install()` function, wire into `main`)

- [ ] **Step 1: Add the `self_install` function above `main`**

```bash
self_install() {
    local src
    src="$(readlink -f "$0")"

    if [[ "$src" != "$INSTALL_PATH" ]]; then
        log "installing self to ${INSTALL_PATH}"
        install -m 0755 "$src" "$INSTALL_PATH"
    fi

    log "writing cron entry to ${CRON_PATH}"
    cat > "$CRON_PATH" <<EOF
# Rebuild the GitHub Actions runner LXC template.
# Generated by build-runner-template.sh — overwritten on every run.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE} root ${INSTALL_PATH} >> /var/log/build-runner-template.log 2>&1
EOF
    chmod 0644 "$CRON_PATH"
}
```

- [ ] **Step 2: Wire `self_install` into `main` (after `preflight`)**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): self-install script + quarterly cron"
```

---

## Task 4: Ensure Ubuntu base template is present

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `ensure_ubuntu_template()` function, wire into `main`)

Background: Proxmox stores LXC base templates under `local:vztmpl/`. We need an `ubuntu-${UBUNTU_VERSION}-standard_*_amd64.tar.zst`. If absent, download with `pveam download local <name>`.

- [ ] **Step 1: Add a global to hold the resolved template filename**

Add this near the top of the `# === Configuration ===` block (after the existing config vars, before `INSTALL_PATH`):

```bash
# Resolved by ensure_ubuntu_template().
UBUNTU_TEMPLATE_FILENAME=""
```

- [ ] **Step 2: Add the `ensure_ubuntu_template` function above `main`**

```bash
ensure_ubuntu_template() {
    log "ensuring ubuntu ${UBUNTU_VERSION} base template is present"

    pveam update >/dev/null

    local existing
    existing="$(pveam list local \
        | awk 'NR>1 {print $1}' \
        | sed 's|^local:vztmpl/||' \
        | grep -E "^ubuntu-${UBUNTU_VERSION}-standard_.*_amd64\.tar\.zst$" \
        | sort \
        | tail -n1 || true)"

    if [[ -n "$existing" ]]; then
        UBUNTU_TEMPLATE_FILENAME="$existing"
        log "found existing template: ${UBUNTU_TEMPLATE_FILENAME}"
        return
    fi

    local available
    available="$(pveam available --section system \
        | awk '{print $2}' \
        | grep -E "^ubuntu-${UBUNTU_VERSION}-standard_.*_amd64\.tar\.zst$" \
        | sort \
        | tail -n1 || true)"

    if [[ -z "$available" ]]; then
        log "no ubuntu ${UBUNTU_VERSION} template available from pveam"
        exit 1
    fi

    log "downloading ${available}"
    pveam download local "$available"
    UBUNTU_TEMPLATE_FILENAME="$available"
}
```

- [ ] **Step 3: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
}
```

- [ ] **Step 4: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): ensure ubuntu base template is downloaded"
```

---

## Task 5: Reset target VMID + create container

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `reset_vmid()` and `create_container()`, wire into `main`)

- [ ] **Step 1: Add `reset_vmid` above `main`**

```bash
reset_vmid() {
    if pct status "$TEMPLATE_VMID" >/dev/null 2>&1; then
        log "destroying existing VMID ${TEMPLATE_VMID}"
        pct stop "$TEMPLATE_VMID" --skiplock >/dev/null 2>&1 || true
        pct destroy "$TEMPLATE_VMID" --purge --force
    else
        log "VMID ${TEMPLATE_VMID} is free"
    fi
}
```

- [ ] **Step 2: Add `create_container` above `main`**

```bash
create_container() {
    log "creating container ${TEMPLATE_VMID}"

    pct create "$TEMPLATE_VMID" "local:vztmpl/${UBUNTU_TEMPLATE_FILENAME}" \
        --hostname runner-template \
        --storage "$STORAGE_POOL" \
        --rootfs "${STORAGE_POOL}:32" \
        --memory 2048 \
        --cores 2 \
        --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
        --features "nesting=1,keyctl=1" \
        --unprivileged 0 \
        --onboot 0 \
        --start 1
}
```

- [ ] **Step 3: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
}
```

- [ ] **Step 4: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): reset VMID and create privileged container"
```

---

## Task 6: Wait for network inside the container

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `wait_for_network()`, wire into `main`)

- [ ] **Step 1: Add `wait_for_network` above `main`**

```bash
wait_for_network() {
    log "waiting for container network"

    local i
    for i in $(seq 1 30); do
        if pct exec "$TEMPLATE_VMID" -- getent hosts github.com >/dev/null 2>&1; then
            log "network up after ${i} attempt(s)"
            return
        fi
        sleep 2
    done

    log "container network did not come up within 60s"
    exit 1
}
```

- [ ] **Step 2: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): wait for container network before exec"
```

---

## Task 7: Install base packages + Playwright system deps

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `install_base_packages()`, wire into `main`)

Background: this is option A from the spec — system libs only, no toolchains. The Playwright deps list covers Chromium, Firefox, and WebKit on Ubuntu 24.04 (noble). If a future Playwright bump adds new required libs, append them here.

- [ ] **Step 1: Add `install_base_packages` above `main`**

```bash
install_base_packages() {
    log "installing base packages and Playwright system deps"

    in_container "$(cat <<'EOF'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg lsb-release \
    git jq sudo \
    build-essential pkg-config \
    libssl-dev libyaml-dev

# Playwright runtime libraries — Chromium + Firefox + WebKit on Ubuntu 24.04.
# Source: github.com/microsoft/playwright (lib/server/registry/dependencies.ts).
# Bump alongside Playwright support changes.
apt-get install -y --no-install-recommends \
    libnspr4 libnss3 libdbus-1-3 \
    libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libxkbcommon0 \
    libpango-1.0-0 libcairo2 libasound2t64 \
    libdbus-glib-1-2 libxt6t64 \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    libavif16 libenchant-2-2 libepoxy0 libevdev2 libgles2 \
    libgstreamer-gl1.0-0 libgstreamer-plugins-base1.0-0 \
    libgudev-1.0-0 libharfbuzz-icu0 libhyphen0 libicu74 \
    libjpeg-turbo8 liblcms2-2 libmanette-0.2-0 \
    libopenjp2-7 libopus0 libpng16-16t64 libsecret-1-0 \
    libsoup-3.0-0 \
    libwayland-client0 libwayland-egl1 libwayland-server0 \
    libwebp7 libwebpdemux2 libwoff1 libx11-xcb1 libxml2

apt-get clean
rm -rf /var/lib/apt/lists/*
EOF
)"
}
```

- [ ] **Step 2: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
    install_base_packages
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): install base packages + Playwright deps"
```

---

## Task 8: Install Docker (upstream apt repo)

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `install_docker()`, wire into `main`)

- [ ] **Step 1: Add `install_docker` above `main`**

```bash
install_docker() {
    log "installing Docker from upstream apt repo"

    in_container "$(cat <<'EOF'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
cat > /etc/apt/sources.list.d/docker.list <<DOCKER
deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable
DOCKER

apt-get update
apt-get install -y --no-install-recommends \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

systemctl enable docker

apt-get clean
rm -rf /var/lib/apt/lists/*
EOF
)"
}
```

- [ ] **Step 2: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
    install_base_packages
    install_docker
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): install Docker from upstream apt"
```

---

## Task 9: Create runner user (docker group + passwordless sudo)

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `create_runner_user()`, wire into `main`)

- [ ] **Step 1: Add `create_runner_user` above `main`**

```bash
create_runner_user() {
    log "creating runner user"

    in_container "$(cat <<'EOF'
set -euo pipefail

if ! id runner >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash runner
fi

usermod -aG docker runner

cat > /etc/sudoers.d/runner <<'SUDO'
runner ALL=(ALL) NOPASSWD:ALL
SUDO
chmod 0440 /etc/sudoers.d/runner
visudo -c -f /etc/sudoers.d/runner
EOF
)"
}
```

- [ ] **Step 2: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
    install_base_packages
    install_docker
    create_runner_user
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): create runner user + sudoers"
```

---

## Task 10: Pin runner version + install runner binary

**Files:**
- Modify: `template-builder/build-runner-template.sh` (set `RUNNER_VERSION` + `RUNNER_SHA256`, add `install_runner_binary()`, wire into `main`)

- [ ] **Step 1: Look up the current runner version + SHA256**

Open https://github.com/actions/runner/releases/latest in a browser.

Find the **release notes** section titled "SHA-256 Checksums". Locate the line for `actions-runner-linux-x64-<version>.tar.gz` — that line gives you both the version (in the filename) and the SHA256 (the hex string before it).

Sanity check from the command line (replace `<version>` with what you saw):

```bash
curl -fsSLo /tmp/runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v<version>/actions-runner-linux-x64-<version>.tar.gz"
sha256sum /tmp/runner.tar.gz
```

The `sha256sum` output must match the SHA256 from the release notes. Record both values for Step 2.

- [ ] **Step 2: Update `RUNNER_VERSION` and `RUNNER_SHA256` in the config block**

In `template-builder/build-runner-template.sh`, replace these two lines:

```bash
RUNNER_VERSION="0.0.0"   # set in Task 10
RUNNER_SHA256="0000000000000000000000000000000000000000000000000000000000000000"  # set in Task 10
```

with the real values from Step 1, for example:

```bash
RUNNER_VERSION="2.323.0"
RUNNER_SHA256="<64-hex-character SHA256 from Step 1>"
```

- [ ] **Step 3: Add `install_runner_binary` above `main`**

```bash
install_runner_binary() {
    log "installing runner ${RUNNER_VERSION}"

    in_container "$(cat <<EOF
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

mkdir -p /opt/runner
cd /opt/runner

curl -fsSLo runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

echo "${RUNNER_SHA256}  runner.tar.gz" | sha256sum -c -

tar xzf runner.tar.gz
rm runner.tar.gz

chown -R runner:runner /opt/runner

# installdependencies.sh pulls libicu and a few other runtime libs the
# runner needs — idempotent against what we already installed.
./bin/installdependencies.sh
EOF
)"
}
```

Note the unquoted `EOF` here — we need `${RUNNER_VERSION}` and `${RUNNER_SHA256}` to expand on the host side before the snippet is sent to the container.

- [ ] **Step 4: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
    install_base_packages
    install_docker
    create_runner_user
    install_runner_binary
}
```

- [ ] **Step 5: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 6: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): pin runner version + install binary"
```

---

## Task 11: Install systemd unit + runner.env placeholder (do not enable)

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `install_systemd_unit()`, wire into `main`)

Spec requirement: install the unit, leave it disabled. The provisioner (PRD 2) writes the real `JITCONFIG` to `/etc/runner.env` and then runs `systemctl enable --now github-runner`.

- [ ] **Step 1: Add `install_systemd_unit` above `main`**

```bash
install_systemd_unit() {
    log "installing /etc/runner.env placeholder + github-runner.service (not enabled)"

    in_container "$(cat <<'EOF'
set -euo pipefail

cat > /etc/runner.env <<'ENV'
# Populated by the provisioner after `pct clone`.
JITCONFIG=
ENV
chown root:runner /etc/runner.env
chmod 0640 /etc/runner.env

cat > /etc/systemd/system/github-runner.service <<'UNIT'
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
UNIT

systemctl daemon-reload
# Intentionally NOT enabled — provisioner enables after writing JITCONFIG.
EOF
)"
}
```

- [ ] **Step 2: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
    install_base_packages
    install_docker
    create_runner_user
    install_runner_binary
    install_systemd_unit
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): install systemd unit + runner.env placeholder"
```

---

## Task 12: Finalise — stop container, convert to template

**Files:**
- Modify: `template-builder/build-runner-template.sh` (add `finalize()`, wire into `main`)

- [ ] **Step 1: Add `finalize` above `main`**

```bash
finalize() {
    log "stopping container ${TEMPLATE_VMID}"
    pct stop "$TEMPLATE_VMID"

    log "converting ${TEMPLATE_VMID} to a template"
    pct template "$TEMPLATE_VMID"

    log "done — template ${TEMPLATE_VMID} built with runner ${RUNNER_VERSION}"
}
```

- [ ] **Step 2: Wire into `main`**

```bash
main() {
    log "build-runner-template.sh starting; VMID=${TEMPLATE_VMID}"
    preflight
    self_install
    ensure_ubuntu_template
    reset_vmid
    create_container
    wait_for_network
    install_base_packages
    install_docker
    create_runner_user
    install_runner_binary
    install_systemd_unit
    finalize
}
```

- [ ] **Step 3: Verify**

```bash
bash -n template-builder/build-runner-template.sh
shellcheck template-builder/build-runner-template.sh
```

Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
git add template-builder/build-runner-template.sh
git commit -m "feat(template-builder): stop and convert to template"
```

---

## Task 13: README

**Files:**
- Create: `template-builder/README.md`

- [ ] **Step 1: Write `template-builder/README.md`**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add template-builder/README.md
git commit -m "docs(template-builder): operator README"
```

---

## Done when

- All 13 tasks committed.
- `bash -n template-builder/build-runner-template.sh` exits 0.
- `shellcheck template-builder/build-runner-template.sh` exits 0 with no findings.
- Operator runs the script on their Proxmox node, gets a template at `TEMPLATE_VMID`, and can `pct clone` it. Runner registration with a JIT config is validated as part of PRD 2.
