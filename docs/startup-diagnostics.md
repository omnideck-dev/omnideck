# Startup failure reporting

The container migration barrier emits `OMNIDECK_STARTUP ` followed by a JSON
record on stderr. The version-1 record contains a UTC timestamp, a `status`
(`starting`, `complete`, or `failed`), a required code-owned `phase`, and an
optional code-owned `step`. The current producer reports phase `migrations`
with a migration identifier as its step. Completion applies only to that phase;
it does not indicate application readiness. The CLI still requires HTTP 2xx.
Failures also contain `code: "MIGRATION_FAILED"`. Exception text, saved records,
credentials, and file contents are deliberately absent from this interface.
Ordinary logs remain available for troubleshooting.

The CLI's application readiness check uses Podman's initial `StartedAt` for the
current check to ignore old failures, including after a successful user retry.
Automatic restarts within that check do not erase a failed migration; completion
of that same phase clears it. A migration failure
returns a nonzero exit with a specific text or JSON explanation. Other valid
phase failures report a general startup error with safe phase/step identifiers.
App images without startup events continue to use HTTP readiness. An exited
container or readiness timeout without a known event returns a generic startup
failure. Checking readiness never removes a container or volume.

Desktop consumes that CLI result through its existing recovery screen, names
the settings-upgrade problem, and offers Technical details, Copy diagnostics,
and Try again. Retry preserves the existing environment; it does not erase or
reset saved data. The application does not serve an error page from a failed
container.

## Delivery dependency

The consumers shipped independently as
[CLI v0.11.0-beta.9](https://github.com/omnideck-dev/cli/releases/tag/v0.11.0-beta.9)
and [Desktop v0.1.0-beta.15](https://github.com/omnideck-dev/omnideck/releases/tag/v0.1.0-beta.15).
Desktop bundles that exact CLI release and retains app 0.5.2. Both consumers
work with existing app releases through HTTP readiness.

Specific migration errors require the app-side producer described above, which
remains on the MCP branch. Shipping the CLI and Desktop does not ship that
producer or MCP integrations. Local development screenshots must identify the
development CLI honestly; they are not release qualification.

## Tests

`tests/unit/migrations/test_startup_report.py` covers safe reporting and ledger
behavior. `tests/unit/migrations/test_startup_report_container.py` runs the real
root entrypoint against an invalid disposable permission record, checks that no
services start, then corrects the fixture and verifies a successful migration
without losing the sentinel data. Set `OMNIDECK_BOOTSTRAP_DISPOSABLE_TEST=1`
only inside a fresh disposable container with no mounted application state.
