#!/bin/bash
#
# build-runner-template.sh — Build a Proxmox LXC template with the
# GitHub Actions runner + Docker + common build/test system libraries.
#
# Run as root on a Proxmox node. See template-builder/README.md.
#
# shellcheck disable=SC2034
# Reason: configuration variables below are referenced by step functions
# wired in across multiple tasks; SC2034 is a known false-positive here.

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
