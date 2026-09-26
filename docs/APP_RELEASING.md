# Releasing the omnideck app

The container-served app at `ghcr.io/omnideck-dev/omnideck` releases independently
from the native desktop host. App versions are plain `X.Y.Z` container tags;
the corresponding GitHub Releases and Git tags are named `app-vX.Y.Z`.
Desktop installers retain their `v*` tags. App releases set `make_latest: false`
so they do not replace the desktop release's Latest designation.

## Automatic Monday releases

**Release container** runs every Monday at **10:00 a.m. America/Chicago**,
including daylight-saving changes. GitHub schedules are best-effort and may
start late. It ships accumulated app changes, or skips when nothing has changed.

1. Read the published container versions and app GitHub Release records,
   including unfinished draft releases.
2. Choose the exact main source commit and compare it with the previous app
   release tag. Combine only new `target: app` fragments into the release notes.
3. Require successful main push CI for that exact source SHA and resolve its
   tested `main-<sha>` multi-architecture image digest.
4. Save a **draft GitHub Release** with the version, rendered notes, source SHA,
   baseline SHA, selected fragments, and tested digest. The machine-readable
   record lives in an HTML comment in the release body.
5. Promote that digest to the versioned GHCR tag, then publish the GitHub
   Release and its `app-vX.Y.Z` tag at the recorded source commit.

The workflow never commits to main, opens a release PR, approves a review, or
removes a fragment. Ordinary code PRs retain the existing branch rules and CI.
It needs `contents: write` for release records/tags, `packages: write` for the
image, and `actions: read` to check source CI. The organization setting allowing
Actions to create or approve PRs is not needed.

## Fragment history and version selection

App fragments stay in `release-notes.d/` as an append-only history. Each release
combines the app fragments added since the previous app release source. Retained
fragments are not repeated in later notes. Do not edit, rename, or delete an
already published app fragment; add a new fragment for a correction. Unreleased
fragments can still be revised in code review. Desktop fragments continue to
follow their independent release process.

Version selection takes the highest required bump:

- **Patch:** fixes, security fixes, maintenance, and ordinary `changed` notes.
- **Minor:** `added` app fragments or app-affecting `feat` commits.
- **Breaking:** `removed` fragments, `bump: major`, a Conventional Commit `!`,
  or a `BREAKING CHANGE:`/`BREAKING-CHANGE:` footer.

During 0.x, a breaking change advances the minor version. From 1.0 onward it
advances the major version. An explicit fragment bump can raise, but cannot
lower, the bump required by its category or commit. Unnoted app maintenance
gets a patch version and a generic maintenance note. Desktop-only and
documentation-only changes do not trigger an app release.

## Manual preview or publication

Preview the version, notes, source CI, and image without writing anything:

```sh
gh workflow run container-release.yml --ref main -f dry_run=true
```

Run the same release flow immediately:

```sh
gh workflow run container-release.yml --ref main
```

An optional `-f version=X.Y.Z` override must be at least the version required by
the accumulated changes. A pending draft must finish before selecting a new
version. Repeating an already published current version verifies the recorded
source and digest without replacing either.

## Failure recovery

The draft release is a durable checkpoint, created before any versioned image
is pushed. A retry resumes that version, source, notes, and digest even if main
has advanced or the image was already published. After a successful retry,
newer work is left for the next run. Do not delete a pending draft or edit its
machine-readable record. Multiple pending app drafts stop the workflow for
operator investigation.

Existing container tags cannot be moved to a different digest. Existing Git
tags cannot be moved to another commit. Registry authentication or network
errors are not interpreted as an unused version. An image without its release
record, a mismatched record, or a missing published image stops publication.

Failed or in-progress source CI also stops publication; rerun after that exact
main source passes. The workflow does not select an older successful commit
and silently omit newer app changes.

## Verify a release

Confirm the workflow passed, compare the version's manifest digest with the
recorded tested digest, and check both architecture entries:

```sh
docker buildx imagetools inspect ghcr.io/omnideck-dev/omnideck:X.Y.Z
gh release view app-vX.Y.Z
```

The release notes are at:

```text
https://github.com/omnideck-dev/omnideck/releases/tag/app-vX.Y.Z
```

## Migration and desktop compatibility

App versions through **0.5.0** used checked-in notes under
`docs/releases/app-vX.Y.Z.md`. They remain available. The first new release uses
the latest legacy version's notes commit as its baseline; subsequent releases
use the published app tag. Versions after 0.5.0 require a GitHub Release record,
so a missing record cannot silently fall back to a guessed baseline.

The **What’s new** URL belongs to the container-served web UI, not the native
installer. Installing the new app image updates both the update notice and
Settings links; a new desktop installer is not required. The URL helper keeps
legacy links for versions through 0.5.0 and uses app GitHub Releases thereafter.
A one-time `app-v0.5.1.md` bridge page supports the initial upgrade from older
UIs. Clients that remain on an older app and skip that transition may still
construct old-style links for later versions until they update; their container
update discovery and installation continue to work.

The desktop updater still discovers plain SemVer tags from GHCR. A desktop
installer pins `desktop/container-version.txt` when it is built; app releases
do not change that installer pin or publish desktop packages.
