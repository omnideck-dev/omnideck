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
type: added
area: desktop
---

Zoom the entire application with Ctrl/Cmd and +, -, or 0. Tabs, menus, and
previews remain aligned at every zoom level.
```

The required fields are:

- `type`: `added`, `changed`, `deprecated`, `removed`, `fixed`, or
  `security`
- `area`: a lowercase kebab-case product or repository area
- body: plain, user-facing prose describing the outcome

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

Generate a release draft from all outstanding fragments:

```sh
node scripts/release-notes.mjs generate --version v1.2.3
node scripts/release-notes.mjs generate \
  --version v1.2.3 \
  --output docs/releases/v1.2.3.md
```

Generation groups fragments into the Keep a Changelog categories. The result is
a draft: before publication, add a short release theme when useful, remove
duplication, confirm upgrade guidance and known limitations, and keep the
language focused on the shipped product.

The release change consumes its fragments after their text is incorporated into
the checked-in release notes or changelog. That release pull request uses
`release-note:none` with a reason explaining that it only aggregates already
reviewed fragments.
