# Top level README design

## Goal

Replace the placeholder top level `README.md` with an open source friendly
overview that converts a curious visitor into either a self host operator or a
contributor. Add a `LICENSE` file (MIT) so the project is legally open source.

## Audience

Layered. A casual visitor lands on the GitHub repo and reads top to bottom.
Operators get what they need (requirements, quick start, links) within the
first screen of scrolling. Contributors get status, design doc pointers, and a
contributing note further down.

## Style constraints

- Short and precise. Aim for roughly 60 to 80 lines of markdown.
- No em dashes or en dashes in prose.
- Concrete language. Avoid filler adjectives.
- Component level details live in `controller/README.md` and
  `template-builder/README.md`. The top level README links to them rather than
  repeating their content.

## Sections

1. **Title plus tagline.** `# lxc-gh-runners` followed by one line:
   "Ephemeral GitHub Actions runners on Proxmox LXC."
2. **Badges.** Two badges only: MIT license and GitHub Actions CI status.
   Repo is `mralanlee/lxc-gh-runners`. Workflow name is `CI`.
   - License: `https://img.shields.io/badge/license-MIT-blue.svg`
   - CI: `https://github.com/mralanlee/lxc-gh-runners/actions/workflows/ci.yml/badge.svg`
3. **What it is.** Two or three sentences. Problem (self hosted runners reuse
   the same machine across jobs, so you have to wipe volumes and caches
   manually or bake cleanup steps into every workflow). Solution (clone an
   LXC template per job, register via JIT config, destroy after the job
   finishes, so there is nothing to clean up).
4. **How it works.** Three or four lines describing the flow:
   GitHub `workflow_job` webhook fires, controller SSHes to the Proxmox host
   and runs `pct clone`, the cloned LXC starts the runner with a JIT config,
   the controller destroys the LXC when the job completes. No diagram.
5. **Components.** Two bullets:
   - `template-builder/` builds the Proxmox LXC template. See
     `template-builder/README.md`.
   - `controller/` is the Python webhook service. See `controller/README.md`.
6. **Requirements.** Bullet list:
   - Proxmox VE node with a storage pool and bridge.
   - GitHub org or repo with a webhook plus a PAT for runner registration.
   - A Docker host to run the controller.
7. **Quick start.** Two numbered steps, each linking to the component README
   for full instructions:
   1. On the Proxmox node, install and run the template builder via
      `curl ... | bash` against the canonical raw URL on `main`. Include a
      short bullet list of what the install does (script copied to
      `/usr/local/sbin/`, cron entry at `/etc/cron.d/build-runner-template`,
      LXC template at VMID 9000 with Ubuntu 24.04, Docker, pinned
      `actions/runner`, and a disabled `github-runner.service` unit) so
      readers know what they are running.
   2. On the Docker host, copy `.env.example`, edit, and run
      `docker compose up`.
8. **Status.** One sentence: "Alpha. Working but expect breaking changes."
9. **Contributing.** One short paragraph. PRs welcome, link to GitHub issues,
   point at `docs/superpowers/specs/` for design docs.
10. **License.** One line: "MIT. See `LICENSE`."

## LICENSE file

Standard MIT license text. Copyright line: `Copyright (c) 2026 Alan Lee`.

## Out of scope

- Logos, screenshots, or animated demos.
- A separate `CONTRIBUTING.md` (the README paragraph is enough for now).
- A separate `CODE_OF_CONDUCT.md`.
- Editing the existing component READMEs.
- Adding new badges beyond license and CI.

## Verification

- `README.md` renders cleanly on GitHub (manual visual check after push).
- All relative links resolve (`controller/README.md`,
  `template-builder/README.md`, `docs/superpowers/specs/`).
- `LICENSE` is recognized by GitHub as MIT (the license badge in the sidebar
  picks it up automatically once the file is present).
