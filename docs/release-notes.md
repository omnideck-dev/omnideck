# Release-note policy

This repository uses [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
for change classification, [Semantic Versioning](https://semver.org/) where the
repository publishes versions, and the change categories from
[Keep a Changelog](https://keepachangelog.com/en/2.0.0/). Release notes are
written for people using the omnideck application, desktop host, and container-served product.

Every pull request must make an explicit release-note decision. The required CI
check accepts exactly one of:

1. one or more new, valid files under `release-notes.d/`; or
2. the `release-note:none` label plus `None: <reason>` under the pull
   request's `## Release note` heading.

Features and breaking changes cannot use `release-note:none`.

## Pull request titles

The pull request title is the canonical machine-readable description and must
use this form:

```text
<type>[optional scope][optional !]: <description>
```

Allowed types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`,
`perf`, `refactor`, `revert`, `style`, and `test`. Examples:

```text
feat(desktop): add native application zoom
fix(cli): preserve the selected runtime port
ci(release): verify published checksums
feat(api)!: remove the legacy profile schema
```

Use a concise technical title. Put polished user-facing copy in the fragment.

## Release-note fragments

Add a short, unique Markdown file such as
`release-notes.d/native-desktop-zoom.md`:

```markdown
---
target: desktop
type: added
area: desktop
---

Zoom the entire application with Ctrl/Cmd and +, -, or 0. Tabs, menus, and
previews remain aligned at every zoom level.
```

The required fields are:

- `target`: `app` for the container-served product or `desktop` for the native
  host, setup, and installers
- `type`: `added`, `changed`, `deprecated`, `removed`, `fixed`, or
  `security`
- `area`: a lowercase kebab-case product or repository area
- body: plain, user-facing prose describing the outcome

Optional `bump: patch|minor|major` metadata can raise the automatic app version
bump. Mark incompatible changes with `bump: major` or a Conventional Commit
breaking marker. `added` requires at least minor; `removed` requires a breaking
bump. During 0.x, breaking changes advance the minor version. See the
[Monday release policy](APP_RELEASING.md#automatic-monday-releases).

Write what changed for the reader and why it matters. Avoid build systems,
test environments, commit hashes, internal refactors, and qualification detail
unless the repository's users must act on them. Include upgrade or migration
guidance when behavior is incompatible.

A pull request may add multiple fragments when it contains distinct notable
changes. Do not combine a fragment with `release-note:none`.

## Changes without release notes

For maintenance that has no externally visible outcome:

1. apply the `release-note:none` label; and
2. write a specific reason in the pull request body:

```markdown
## Release note

None: Expands release qualification only; shipped behavior is unchanged.
```

The explicit reason makes omissions reviewable. `feat` titles and titles with
`!` must provide fragments instead.

## Validation and generation

Run the shared local checks:

```sh
node --test tests/release-notes.test.mjs
node scripts/release-notes.mjs validate-fragments
```

Desktop releases generate a draft from their outstanding fragments:

```sh
node scripts/release-notes.mjs generate \
  --target desktop \
  --version v1.2.3 \
  --output docs/releases/v1.2.3.md
```

Desktop preparation consumes only desktop fragments after incorporating them
into the checked-in notes. That release PR uses `release-note:none` with a
reason explaining that it aggregates already reviewed fragments.

App fragments are retained permanently. Once published, add a new fragment
for a correction rather than editing, renaming, or deleting an existing one.
The app planner combines only new app fragments since the previous release
source, grouping them into Keep a Changelog categories. It does not include
retained notes from earlier versions or desktop fragments.

## App publication

Follow the [app release runbook](APP_RELEASING.md). The [Monday
workflow](APP_RELEASING.md#automatic-monday-releases) selects a version and exact
tested main image, saves a draft release checkpoint, promotes the image by
digest, then publishes the `app-vX.Y.Z` GitHub Release. No release-preparation
PR or fragment deletion is required. Preview it with:

```sh
gh workflow run container-release.yml --ref main -f dry_run=true
```

The GitHub Release body is the app changelog and includes a hidden source/digest
record for safe retries. Container tags stay plain `X.Y.Z`; desktop release
tags stay `v*`. App releases are not marked Latest. **What’s new** in the
container-served UI opens the app release page. Versions through 0.5.0 keep
their historical checked-in notes; see the runbook for migration details.
