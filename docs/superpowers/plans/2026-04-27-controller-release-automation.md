# Controller Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate semver-based releases of the `controller/` service — git tags, GitHub releases, CHANGELOG, and Docker image tags — using release-please.

**Architecture:** A single workflow on `main` runs three jobs: `test` (existing), `release-please` (manages a Release PR and cuts tags on merge), and `build-and-push` (builds the controller image; adds the semver tag ladder when release-please cut a release on this push). release-please runs in monorepo manifest mode with `controller` as the only configured package.

**Tech Stack:** GitHub Actions, `googleapis/release-please-action@v4`, `docker/metadata-action@v5`, `docker/build-push-action@v6`.

**Spec:** `docs/superpowers/specs/2026-04-27-controller-release-design.md`

---

## File Structure

Files created:
- `release-please-config.json` — release-please configuration (repo root, manifest mode)
- `.release-please-manifest.json` — release-please version manifest (repo root)
- `controller/CHANGELOG.md` — empty bootstrap; release-please maintains this going forward

Files modified:
- `.github/workflows/ci.yml` — expand top-level `permissions:`; add `release-please` job; rename existing `release` job to `build-and-push` (its real role) and wire it to the release-please outputs
- `controller/pyproject.toml` — add release-please version annotation comment

Existing files unchanged:
- `controller/Dockerfile`, `controller/docker-compose.yml`, all of `template-builder/`, all of `controller/src/` and `controller/tests/`

---

### Task 1: Bootstrap release-please configuration

**Files:**
- Create: `release-please-config.json`
- Create: `.release-please-manifest.json`
- Create: `controller/CHANGELOG.md`
- Modify: `controller/pyproject.toml` (add annotation comment on the `version` line)

- [ ] **Step 1: Create `release-please-config.json`**

Write the file at the repo root with this exact content:

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

The `"controller"` key is the package directory path (release-please scopes commit detection to files under this path). `include-component-in-tag: true` produces tags shaped `controller-v0.1.0`, leaving namespace for a future `template-builder-v…`. `extra-files` is matched against the version annotation we add to `pyproject.toml` in step 4 below.

- [ ] **Step 2: Create `.release-please-manifest.json`**

Write the file at the repo root with this exact content (must match the current `controller/pyproject.toml` version):

```json
{
  "controller": "0.1.0"
}
```

- [ ] **Step 3: Create empty `controller/CHANGELOG.md`**

Write a one-line bootstrap that release-please will populate on the first release:

```markdown
# Changelog
```

- [ ] **Step 4: Annotate `controller/pyproject.toml` version line**

Open `controller/pyproject.toml`. The current first three lines are:

```toml
[project]
name = "controller"
version = "0.1.0"
```

Change line 3 to:

```toml
version = "0.1.0" # x-release-please-version
```

The `# x-release-please-version` comment marks the line release-please rewrites when bumping the version (this is what makes `extra-files: ["pyproject.toml"]` actually do something — without it, the entry is a no-op).

- [ ] **Step 5: Validate JSON files parse**

Run from the repo root:

```bash
python3 -m json.tool < release-please-config.json > /dev/null && python3 -m json.tool < .release-please-manifest.json > /dev/null && echo OK
```

Expected output: `OK`. If either file fails, fix the JSON and re-run.

- [ ] **Step 6: Verify the controller test suite still passes**

The pyproject change is a comment, not a value change. Confirm nothing broke:

```bash
cd controller && uv sync --extra dev && uv run pytest -v
```

Expected: all tests pass (same set as before this task).

- [ ] **Step 7: Commit**

```bash
git add release-please-config.json .release-please-manifest.json controller/CHANGELOG.md controller/pyproject.toml
git commit -m "ci: add release-please configuration for controller"
```

---

### Task 2: Add `release-please` job to CI workflow

**Files:**
- Modify: `.github/workflows/ci.yml` (top-level `permissions:` block, new `release-please` job inserted between `test` and the existing `release` job)

- [ ] **Step 1: Expand top-level workflow permissions**

In `.github/workflows/ci.yml`, the current `permissions:` block (lines 8-10) is:

```yaml
permissions:
  contents: read
  packages: write
```

Replace with:

```yaml
permissions:
  contents: write
  packages: write
  pull-requests: write
```

- `contents: write` — release-please needs to push tags and commit changelog updates to the Release PR.
- `pull-requests: write` — release-please opens and updates the Release PR.
- `packages: write` — unchanged; the build job needs it to push to GHCR.

- [ ] **Step 2: Add the `release-please` job**

In `.github/workflows/ci.yml`, after the existing `test` job ends (after line 40, the `uv run pytest -v` step) and before the `release:` job header, insert:

```yaml
  release-please:
    name: Release-please
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    outputs:
      release_created: ${{ steps.release.outputs['controller--release_created'] }}
      tag_name: ${{ steps.release.outputs['controller--tag_name'] }}
      major: ${{ steps.release.outputs['controller--major'] }}
      minor: ${{ steps.release.outputs['controller--minor'] }}
      patch: ${{ steps.release.outputs['controller--patch'] }}
    steps:
      - uses: googleapis/release-please-action@v4
        id: release
        with:
          config-file: release-please-config.json
          manifest-file: .release-please-manifest.json
```

The `outputs:` block re-exports release-please-action's component-prefixed outputs (`controller--*`) under simpler names so the next job can consume them as `needs.release-please.outputs.major` rather than re-typing the prefix string. The `if:` condition matches the existing build job — release-please only acts on pushes to `main`, never on PRs.

- [ ] **Step 3: Verify the workflow YAML parses**

Run from the repo root:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo OK
```

Expected: `OK`. If `pyyaml` is missing, install it first: `python3 -m pip install --user pyyaml`. If parsing fails, the error message will name the line — most commonly an indentation issue.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add release-please job to manage controller releases"
```

---

### Task 3: Rename `release` job to `build-and-push` and wire it to release-please outputs

**Files:**
- Modify: `.github/workflows/ci.yml` (rename existing `release` job to `build-and-push`, add `release-please` to `needs:`, expand image tag rules)

- [ ] **Step 1: Rename the job and add the `release-please` dependency**

The existing job header is:

```yaml
  release:
    name: Build and push image
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
```

Change the job key from `release` to `build-and-push` and update `needs:`:

```yaml
  build-and-push:
    name: Build and push image
    needs: [test, release-please]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
```

The `release` name was misleading once release-please owns the actual release-cutting; `build-and-push` reflects what this job actually does.

- [ ] **Step 2: Update the `metadata-action` tag rules**

Find the `Compute image metadata` step. Its `tags:` block is currently:

```yaml
          tags: |
            type=raw,value=latest
            type=sha,format=short
```

Replace with:

```yaml
          tags: |
            type=raw,value=latest
            type=sha,format=short
            type=raw,value=${{ needs.release-please.outputs.major }},enable=${{ needs.release-please.outputs.release_created == 'true' }}
            type=raw,value=${{ needs.release-please.outputs.major }}.${{ needs.release-please.outputs.minor }},enable=${{ needs.release-please.outputs.release_created == 'true' }}
            type=raw,value=${{ needs.release-please.outputs.major }}.${{ needs.release-please.outputs.minor }}.${{ needs.release-please.outputs.patch }},enable=${{ needs.release-please.outputs.release_created == 'true' }}
```

Each new `type=raw` entry is gated by `enable=${{ ... == 'true' }}`. On a normal push to `main` (no release cut), `release_created` is the empty string and `enable` evaluates false — only `latest` and `sha-<short>` get tagged (the existing behavior). On the push that merges the Release PR, `release_created` is `'true'` and the full ladder (`0.1.1`, `0.1`, `0`) is added in the same `metadata-action` call, then pushed in the same `build-push-action` call — so all tags appear together atomically.

- [ ] **Step 3: Verify the workflow YAML parses**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo OK
```

Expected: `OK`. If parsing fails, the most common cause is inconsistent indentation inside the `|` block-scalar; ensure all five tag entries are at the same column.

- [ ] **Step 4: Read the full file and sanity-check**

Open `.github/workflows/ci.yml` and confirm:

- Top-level `permissions:` has `contents: write`, `packages: write`, `pull-requests: write`.
- Three jobs in order: `test`, `release-please`, `build-and-push`.
- `release-please` has `needs: test` and an `outputs:` block.
- `build-and-push` has `needs: [test, release-please]`.
- The `tags:` block has 5 entries: `latest`, `sha`, and three `type=raw` semver entries each with an `enable=` predicate.
- No leftover job named `release`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: tag controller image with semver on release-please releases"
```

---

### Task 4: Push the branch, open a PR, and verify behavior

- [ ] **Step 1: Push the branch**

```bash
git push -u origin mralanlee/release-action
```

- [ ] **Step 2: Open a PR**

```bash
gh pr create --base main --title "ci: automated controller releases via release-please" --body "$(cat <<'EOF'
## Summary

- Adds release-please configuration in monorepo manifest mode (`controller` package only).
- New `release-please` job opens/updates a Release PR on each push to main and cuts a `controller-vX.Y.Z` tag + GitHub release when that PR is merged.
- Renames the existing `release` job to `build-and-push` and adds semver image tags (`X.Y.Z`, `X.Y`, `X`) when a release is cut, alongside the existing `latest` and `sha-<short>` tags.

Spec: `docs/superpowers/specs/2026-04-27-controller-release-design.md`

## Test plan

- [x] PR CI passes (test job).
- [ ] After merge: a Release PR titled like `chore(controller): release X.Y.Z` appears on main.
- [ ] After merging the Release PR: a `controller-vX.Y.Z` git tag and GitHub release exist; the controller image on GHCR has tags `X.Y.Z`, `X.Y`, `X`, `latest`, and `sha-<short>`.
EOF
)"
```

- [ ] **Step 3: Watch CI on the PR**

```bash
gh pr checks --watch
```

Expected: the `test` job passes. The `release-please` and `build-and-push` jobs are skipped on PRs because both have `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`. Skipped is the correct outcome here — the workflow only does anything on `main`.

- [ ] **Step 4: Merge to main, then observe the first Release PR**

After merging this PR, on the next `main` push the `release-please` job runs and (because there is no existing `controller-v*` tag) opens a Release PR.

```bash
gh pr list --search "release-please"
```

Expected: a PR titled like `chore(controller): release 0.X.Y`. release-please keeps this PR updated as additional commits land on `main`; do not merge it until you intend to cut a release.

- [ ] **Step 5: When ready to cut a release, merge the Release PR and verify**

After the Release PR is merged:

```bash
git fetch --tags
git tag --list 'controller-v*'
gh release list --limit 5
```

Expected: a new `controller-vX.Y.Z` tag and a corresponding GitHub release with auto-generated notes.

Then verify image tags by pulling:

```bash
docker pull ghcr.io/<owner>/lxc-gh-runners/controller:0.X.Y
docker pull ghcr.io/<owner>/lxc-gh-runners/controller:0.X
docker pull ghcr.io/<owner>/lxc-gh-runners/controller:0
docker pull ghcr.io/<owner>/lxc-gh-runners/controller:latest
```

(Substitute `<owner>` with the GitHub org or user that owns this repo.) All four should pull successfully and resolve to the same digest.

If any of the semver tags is missing, check the `build-and-push` workflow run's log for the `Compute image metadata` step — its `tags` output should list all five tag values. The most common cause of a missing semver tag is the `enable=` expression evaluating false because `release_created` is something other than the literal string `'true'`.

---

## Notes for the implementer

- **Do not amend commits across tasks.** Each task ends with its own commit so the history is reviewable.
- **The image tagging is idempotent.** Re-running the workflow on the same release SHA re-pushes the same tags to the same digest — safe.
- **release-please is stateless.** It rederives everything from git tags and the manifest file on every run. There is no `.release-please-state` to maintain.
- **Adding `template-builder` later** is a single new entry in `release-please-config.json`'s `packages` map plus a `"template-builder": "0.0.0"` entry in the manifest. No workflow changes needed unless template-builder gets its own image (it currently doesn't).
