# lxc-gh-runners

Ephemeral GitHub Actions runners on Proxmox LXC.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/mralanlee/lxc-gh-runners/actions/workflows/ci.yml/badge.svg)](https://github.com/mralanlee/lxc-gh-runners/actions/workflows/ci.yml)

## What it is

Self hosted GitHub Actions runners are stateful by default. They accumulate
build artifacts, leak credentials between jobs, and are slow to clean up. This
project provisions a fresh LXC container for every job and destroys it the
moment the job finishes.

## How it works

A `workflow_job` webhook fires when GitHub queues a job. The controller SSHes
to the Proxmox host and runs `pct clone` against a prebuilt template. The
cloned LXC starts the runner with a JIT registration token, runs the job, and
the controller destroys the LXC when the job completes.

## Components

- [`template-builder/`](template-builder/README.md) is a bash script that
  builds the Proxmox LXC template (Ubuntu base, Docker, pinned `actions/runner`).
- [`controller/`](controller/README.md) is the Python webhook service that
  clones, registers, and reaps runners.

## Requirements

- A Proxmox VE node with a storage pool and a network bridge.
- A GitHub org or repo with a webhook configured and a PAT scoped for runner
  registration.
- A Docker host to run the controller.

## Quick start

1. On the Proxmox node, as root, install and run the template builder:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/mralanlee/lxc-gh-runners/main/template-builder/build-runner-template.sh | bash
   ```
   This:
   - copies the script to `/usr/local/sbin/build-runner-template.sh`,
   - writes a quarterly rebuild cron entry at `/etc/cron.d/build-runner-template`,
   - builds a Proxmox LXC template at VMID 9000 containing Ubuntu 24.04,
     Docker, the pinned `actions/runner` release, and a disabled
     `github-runner.service` unit.

   See [`template-builder/README.md`](template-builder/README.md) for
   configuration overrides and runner version bumps.

2. On the Docker host, run the controller:
   ```bash
   cd controller && cp .env.example .env  # edit with your values
   docker compose up --build -d
   ```
   See [`controller/README.md`](controller/README.md) for required
   environment variables and the GitHub webhook setup.

## Status

Alpha. Working but expect breaking changes.

## Contributing

PRs welcome. File an [issue](https://github.com/mralanlee/lxc-gh-runners/issues)
to start a discussion. Design docs live under
[`docs/superpowers/specs/`](docs/superpowers/specs/).

## License

MIT. See [`LICENSE`](LICENSE).
