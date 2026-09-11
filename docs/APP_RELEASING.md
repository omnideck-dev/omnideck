# Releasing the omnideck app

The omnideck app is the container-served product published at
`ghcr.io/omnideck-dev/omnideck`. It releases independently from the native
desktop host and uses plain Semantic Versions such as `0.2.2`.

GitHub Releases remain reserved for downloadable desktop installers. Each app
release instead publishes a versioned container tag and keeps its user-facing
notes at `docs/releases/app-vX.Y.Z.md`. The desktop update notice and Settings
open that file through **What’s new**.

The Friday workflow automates this process; see [Automatic Friday releases](#automatic-friday-releases).
The following steps remain available for manual releases.

## 1. Prepare the release notes

Start from the current `main` branch in a dedicated release worktree. Choose the
next plain `X.Y.Z` version, validate the outstanding fragments, and generate the
app draft:

```sh
VERSION=0.2.2
node scripts/release-notes.mjs validate-fragments
node scripts/release-notes.mjs generate \
  --target app \
  --version "${VERSION}" \
  --output "docs/releases/app-v${VERSION}.md"
```

The generator selects only `target: app` fragments and groups them using the
Keep a Changelog categories. It does not consume desktop fragments.

Review the generated file before publication. Keep its first line exactly
`# omnideck app X.Y.Z`, remove duplication, and make the body describe the
user-visible outcome. Add upgrade guidance or known limitations when relevant.

Remove only the app fragments incorporated into the reviewed release file,
then verify that no app fragments remain unconsumed:

```sh
node scripts/release-notes.mjs check-consumed --target app
node --test tests/release-notes.test.mjs
git diff --check
```

Open and merge a release-preparation pull request. Because that pull request
only aggregates previously reviewed fragments, apply `release-note:none` and
include a specific reason such as:

```markdown
None: This pull request only aggregates previously reviewed app release-note fragments.
```

## 2. Confirm the tested image

Wait for the merge commit's required `main` checks to pass. The CI workflow
builds and tests the multi-architecture image before publishing the candidate
tag `main-<seven-character-commit>`.

Do not release from another branch or from a commit whose candidate image did
not complete the required tests. The release workflow promotes that exact
candidate; it does not rebuild the product.

## 3. Promote the container version

Run the **Release container** workflow from `main` with the plain version:

```sh
gh workflow run container-release.yml \
  --repo omnideck-dev/omnideck \
  --ref main \
  -f version="${VERSION}"
```

The workflow automatically:

- validates the plain `X.Y.Z` version;
- requires `docs/releases/app-vX.Y.Z.md` with the matching heading;
- refuses to proceed while any `target: app` fragments remain;
- resolves the tested `main-<commit>` multi-architecture image;
- promotes that exact digest to `ghcr.io/omnideck-dev/omnideck:X.Y.Z`; and
- refuses to move an existing version tag to a different digest.

It does not create a Git tag, a GitHub Release, or desktop installers.

## 4. Verify the release

Confirm the workflow completed successfully and inspect the published manifest:

```sh
docker buildx imagetools inspect \
  "ghcr.io/omnideck-dev/omnideck:${VERSION}"
```

Open the version's rendered notes at:

```text
https://github.com/omnideck-dev/omnideck/blob/main/docs/releases/app-vX.Y.Z.md
```

The desktop updater discovers plain Semantic Version tags from GHCR. When it
offers this version, both update surfaces derive the same notes URL from the
detected version.

## Relationship to desktop releases

A desktop installer pins the app version selected in
`desktop/container-version.txt` when that installer is built. Later app
releases do not modify an existing desktop installer, and a desktop release is
not required for each app release. Change the desktop pin only when a future
desktop installer should start from a different app version.

## Automatic Friday releases

**Release container** runs every Friday at **10:00 a.m. America/Chicago**,
including daylight-saving changes. [GitHub schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
are best-effort and may start late. Leave `version` blank when dispatching it manually to use the same
planner. Set `dry_run` to preview the version and notes and verify the source
without writing to Git or publishing a tag:

```sh
gh workflow run container-release.yml --ref main -f dry_run=true
```

The planner reads all published package versions from GHCR through the GitHub
Packages API and uses the highest plain Semantic Version as the baseline.
It considers accumulated app fragments and app source changes since that
version's notes were added. Desktop-only, documentation-only, and empty weeks
are skipped. App maintenance without a fragment receives a patch version and
a generic maintenance note.

Version selection takes the highest of:

- **Patch:** fixes, security fixes, and maintenance.
- **Minor:** `added` app fragments or app-affecting `feat` commits.
- **Breaking:** `removed` app fragments, `bump: major`, a Conventional Commit
  `!`, or a `BREAKING CHANGE:`/`BREAKING-CHANGE:` footer.

During 0.x, breaking changes advance the minor version, for example 0.3.1 →
0.4.0. From 1.0 onward they advance the major version. A fragment can explicitly
request `bump: patch`, `bump: minor`, or `bump: major`; this can raise but cannot
lower a bump required by its category or commit. `changed` defaults to patch,
so authors must mark incompatible changes explicitly. Automation cannot infer
compatibility reliably from prose or code. Promote to 1.0 intentionally using
the manual release process and version input.

Before any write, the workflow requires successful main push CI for the exact
source SHA and resolves its tested `main-<sha>` image digest. It then generates
notes from the already-reviewed fragments, consumes only app fragments, and
commits those files plus `docs/releases/app-vX.Y.Z.json` directly to main with
the repository's `GITHUB_TOKEN`. The record pins the source SHA and previous
version. A concurrent main push aborts preparation; it is never force-pushed.
The image is promoted by digest without rebuilding.

This is an explicit automatic exception to the manual release-preparation PR:
only generated release metadata is committed by the bot. The existing reviewed
app source must already have passed CI. Bot pushes do not start another CI
run, so the notes commit is intentionally not the image source. Future branch
rules must permit this metadata push, or the workflow will fail without
publishing; it does not bypass protection or require a personal token.

If notes were committed but publication failed, the next blank-version run
resumes that exact version and source, even if more changes have since merged.
Existing manually prepared release notes resume from their own tested commit.
Multiple unpublished versions stop automation for operator resolution. Existing
version tags are immutable: a retry succeeds only if the digest matches.

A failure or in-progress CI stops that Friday run; it does not fall back to an
older source. Rerun after CI passes. Newer work accumulated while resuming a
pending release remains for the following run. Desktop installers retain their
independent release process.
