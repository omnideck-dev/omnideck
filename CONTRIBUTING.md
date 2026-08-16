# Contributing to omnideck

Keep pull requests focused, explain the outcome, and include the relevant
automated and manual verification.

## Pull request requirements

- Use a [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/)
  title such as `feat(desktop): add native zoom` or
  `fix(setup): recover from an occupied port`.
- Add a user-facing file under `release-notes.d/`, or apply
  `release-note:none` and explain `None: <reason>` under the pull request's
  `## Release note` heading.
- Update documentation and tests when behavior changes.
- Run the repository's documented quality checks before requesting review.

Read [the release-note policy](docs/release-notes.md) for fragment categories,
examples, validation, and release generation.
