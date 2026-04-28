# Controller release automation — design

**Status:** approved
**Date:** 2026-04-27
**Scope:** `controller/` only. `template-builder/` is intentionally not released yet but the configuration is structured so adding it later is a one-line change.

## Goal

When a new version of the controller is ready, automatically:

1. Pick the next semver version from conventional commits.
2. Create a git tag and GitHub release.
3. Build the Docker image with semver tags so consumers can pin to whatever stability level they want.

Releases must be a deliberate, reviewable action — not automatic on every push.

## Approach

`release-please` (Google) in **manifest mode**. It opens a "Release PR" that bumps the version and updates the changelog. Merging the PR creates the tag and GitHub release, which the same workflow then uses to tag the image with semver.

Why release-please over alternatives:
- Aligns with the existing conventional-commit style (`feat:`, `fix:`).
- Manifest mode is monorepo-aware: configuration is structured to add `template-builder` later without migration.
- The Release PR is a human-reviewable gate — matches the requirement that releases are deliberate.

Rejected:
- `semantic-release` — fully automatic, no review gate. Wrong fit.
- Manual `vX.Y.Z` tagging — works but doesn't automate version selection or changelog generation.

## Workflow shape

A single workflow on `main` (`.github/workflows/ci.yml`) runs three jobs:

1. **`test`** — existing ruff + pytest job. Gates everything.
2. **`release-please`** — runs `googleapis/release-please-action@v4` with the config files below. On a normal push it may open or update the Release PR. When the Release PR is merged, this job emits `release_created: true` and the version components as outputs.
3. **`build-and-push`** — `needs: [test, release-please]`. Builds the controller image and pushes to GHCR. Tags are computed conditionally on release-please's outputs (see "Image tag scheme").

Permissions on the workflow: `contents: write`, `pull-requests: write`, `packages: write`.

## Configuration files

### New: `release-please-config.json`

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": {
    "controller": {
      "release-type": "python",
      "package-name": "controller",
      "include-component-in-tag": true,
      "extra-files": ["pyproject.toml"]
    }
  }
}
```

- `release-type: python` — release-please knows how to bump `version = "x.y.z"` in `pyproject.toml` and produce a Python-style CHANGELOG.
- `include-component-in-tag: true` — produces tags like `controller-v0.1.0` (vs. plain `v0.1.0`), reserving namespace for `template-builder-vX.Y.Z` later.
- `extra-files: ["pyproject.toml"]` — explicit so the version is bumped in addition to whatever the python release-type touches by default.

### New: `.release-please-manifest.json`

```json
{
  "controller": "0.1.0"
}
```

Bootstraps from the current `pyproject.toml` value.

### New: `controller/CHANGELOG.md`

Maintained by release-please. Bootstrap empty.

### Modified: `.github/workflows/ci.yml`

Add the `release-please` job. Modify the existing build job to:

- Add `needs: release-please` to its existing `needs: test`.
- Update the `docker/metadata-action` step's `tags:` to add the semver ladder, gated on `release-please`'s `release_created` output.

Sketch of the tag rules:

```yaml
tags: |
  type=raw,value=latest
  type=sha,format=short
  type=raw,value=${{ needs.release-please.outputs['controller--major'] }},enable=${{ needs.release-please.outputs['controller--release_created'] == 'true' }}
  type=raw,value=${{ needs.release-please.outputs['controller--major'] }}.${{ needs.release-please.outputs['controller--minor'] }},enable=${{ needs.release-please.outputs['controller--release_created'] == 'true' }}
  type=raw,value=${{ needs.release-please.outputs['controller--major'] }}.${{ needs.release-please.outputs['controller--minor'] }}.${{ needs.release-please.outputs['controller--patch'] }},enable=${{ needs.release-please.outputs['controller--release_created'] == 'true' }}
```

In manifest mode, release-please-action prefixes outputs with the package name and `--`, so the controller's outputs are `controller--release_created`, `controller--major`, `controller--minor`, `controller--patch`, `controller--tag_name`, etc.

## Image tag scheme

| Trigger                                    | Tags pushed                                                  |
|--------------------------------------------|--------------------------------------------------------------|
| Push to `main`, no release cut             | `latest`, `sha-<short>`                                       |
| Push to `main` that merges the Release PR  | `latest`, `sha-<short>`, `0.1.0`, `0.1`, `0` (semver ladder) |

All tags are produced in one `metadata-action` invocation and pushed in one `build-push-action` invocation, so there is no window where some tags exist and others don't.

The `controller-` git-tag prefix is *not* mirrored to image tags — the image path is already `ghcr.io/<repo>/controller`, so the prefix would be redundant.

## Versioning rules

Pre-1.0 (`0.x.y`), release-please's defaults apply:

- `feat:` → minor bump
- `fix:`, `perf:`, `refactor:` → patch bump
- `feat!:` / `BREAKING CHANGE:` footer → still minor in 0.x (intentional; only ≥1.0 makes it major)
- Other types (`chore:`, `docs:`, `test:`, `ci:`) don't trigger a release

If breaking changes during 0.x should force 1.0.0 immediately, add `"bump-minor-pre-major": false` to the controller config. Default behavior is fine for now.

## Commit scoping

release-please only considers commits whose file changes touch the package's path. With the controller package mapped to `controller/`:

- Commits touching `controller/**` → considered for controller release.
- Commits touching only `template-builder/**`, root files, or `.github/**` → ignored for controller release.
- Mixed commits → considered (the controller part counts).

This is the desired behavior: template-builder changes don't bump the controller version.

## Bootstrapping behavior

First run after this lands:

1. release-please sees no existing `controller-v*` tag and the manifest says `0.1.0`.
2. It walks all commits in `controller/**` since project inception (commit `9ba28ac`'s tree, where `controller/` was introduced).
3. It opens a Release PR proposing the first version. The bump from the bootstrap `0.1.0` depends on commit types since the controller landed — likely `0.2.0` if any `feat:` exists, otherwise `0.1.1`.
4. Merging that PR creates `controller-v0.X.Y`, the GitHub release, the changelog entry, and triggers the image with semver tags.

Subsequent runs are incremental from the previous tag.

## Failure modes

- **`release-please` job fails** → `build-and-push` is skipped (gated by `needs:`). No image is built. Fix and re-push.
- **`build-and-push` fails after `release-please` cut a tag** → the git tag and GitHub release exist, but the image with semver tags does not. Re-running the workflow on the same SHA rebuilds the image; the metadata step is idempotent against the same tag values.
- **Workflow re-run on a SHA where the Release PR was already merged** → release-please sees the tag exists and emits `release_created: false`. The semver tags are *not* re-pushed. `latest` / `sha-<short>` are. Acceptable.

## Out of scope

- Release-notes customization beyond release-please defaults
- SBOM generation, image signing (cosign), provenance attestations
- template-builder releases (config slot reserved; populate when needed)
- Pulling unreleased pre-release tags (e.g., `0.2.0-rc.1`) — not configured

## Files changed summary

- `release-please-config.json` (new)
- `.release-please-manifest.json` (new)
- `controller/CHANGELOG.md` (new, empty bootstrap)
- `.github/workflows/ci.yml` (modified: add `release-please` job, update build job's `needs:` and image-tag rules, expand workflow `permissions:`)
