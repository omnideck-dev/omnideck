# Releasing the omnideck app

The omnideck app is the container-served product published at
`ghcr.io/omnideck-dev/omnideck`. It releases independently from the native
desktop host and uses plain Semantic Versions such as `0.2.2`.

GitHub Releases remain reserved for downloadable desktop installers. Each app
release instead publishes a versioned container tag and keeps its user-facing
notes at `docs/releases/app-vX.Y.Z.md`. The desktop update notice and Settings
open that file through **What’s new**.

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
