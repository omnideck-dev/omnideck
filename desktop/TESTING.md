# OmniDeck desktop testing policy

This document is the authoritative source for desktop test requirements,
release evidence, supported package matrices, and promotion gates.
[`RELEASING.md`](RELEASING.md) defines tagging, approval, and publication
mechanics. Suite-specific instructions live beside each suite.

The canonical setup experience contract lives in
[`tests/setup-ux-principles.md`](tests/setup-ux-principles.md). Setup tests and
manual procedures must preserve it across every operating system.

A passing build proves only its stated layer. Compilation is not installation,
a cross-build is not native execution, and an unexecuted manual procedure is
`blocked` coverage rather than a pass. Electron user-state migration is an
explicit non-goal; the frozen Electron fixtures test setup parity only.

## Test layers

| Layer | Implementation | Where it runs | Required evidence |
| --- | --- | --- | --- |
| Source | Node policy/parity and release-contract unit tests; Rust format, unit, and Clippy checks; pinned sidecar verification | Pull requests, `main`, and tags on hosted CI; locally | Exact commit and command or Actions run |
| Release contract | [`tests/releasecontract`](tests/releasecontract/README.md) | Before publication and against public release assets | JSON report, checksums, and attestations |
| Native packaged smoke | [`tests/hardware`](tests/hardware/README.md) | Dedicated real-OS machines or opt-in self-hosted workflow | Application hash, host inventory, logs, and read-only smoke proof |
| Automated VM journey | [`tests/e2e`](tests/e2e/README.md) | Disposable local Linux/Windows VM lab | Package hash, live DOM/copy states, screenshots, inventories, JSON summary, and JUnit |
| Manual journey | [`tests/manual`](tests/manual/README.md) | Disposable VMs or dedicated hardware | Completed procedure with screenshots, inventories, cleanup, and pass/fail/blocked result |

Hosted CI owns deterministic source, supply-chain, build, and static artifact
checks. Native hardware owns installation, display-server integration, GUI
launch, packaged sidecar execution, and OS-specific behavior. The local VM E2E
suite automates the real packaged setup/hosted/recovery and package lifecycle
that native WebDriver and OS tooling can observe repeatably. Manual testing owns
secure-desktop/reboot boundaries, trust warnings, subjective visual quality,
and timing-dependent destructive recovery. No earlier layer substitutes for a
later one, and the automated suite records its manual remainder as `not-run`.

In this policy, `offline hardware/manual` means outside the always-on hosted CI
path; it does not necessarily mean disconnected from the network. A genuinely
network-disconnected source build uses the verified archive cache described
below.

## Execution and gating matrix

| Tier | Owner | Environment | Destructive scope | Typical time | Gate |
| --- | --- | --- | --- | --- | --- |
| Source | Desktop code owner | GitHub-hosted runner or developer machine | None outside build/cache files | 10-25 minutes | Pull request merge and tag |
| Build + release contract | Release workflow | Six hosted build targets plus Ubuntu aggregator | None outside build artifacts | Up to 90 minutes | Protected publication approval |
| Published release contract | Release owner | GitHub-hosted Ubuntu, public assets | None | 10-20 minutes | Candidate qualification |
| Native packaged smoke | Platform tester assigned in the candidate record | Dedicated Windows/macOS/Linux desktop session | Windows installs the app; other runs mount/extract packages | 10-30 minutes per target | Architecture/package qualification |
| Automated packaged journey | Desktop release owner | Disposable local Linux/Windows VM lab | Resets one leased guest and creates isolated app/runtime state | 20-90 minutes per lane | Local candidate regression gate |
| Clean first run and recovery | Platform tester assigned in the candidate record | Disposable machine or restorable VM | May install runtimes, change WSL/features, reboot, and create containers/volumes | 1-3 hours per platform | Channel promotion |
| Visual/platform fit | Human platform reviewer assigned in the candidate record | Representative displays and desktops | App/runtime state only | 30-60 minutes per platform | Beta, RC, and stable promotion |

The candidate record must name people or agents for every non-CI row. An
unassigned owner is itself blocked coverage.

## Canonical source verification

From `desktop/`, run:

```sh
pnpm install --frozen-lockfile
pnpm run verify
```

`pnpm run verify` downloads or reads the six pinned CLI archives, verifies
their archive, executable, SBOM, format, and architecture hashes, runs Node
tests, checks Rust formatting, runs Rust tests, and runs Clippy with warnings
denied.

For a disconnected or sandboxed build, populate a directory with the exact
archives and SBOMs named by `src-tauri/binaries/vendor-manifest.json`, then set
`OMNIDECK_CLI_ARCHIVE_DIR`. Offline input never disables hashes:

```sh
OMNIDECK_CLI_ARCHIVE_DIR=/verified/cli-assets pnpm run verify
```

If the host does not provide Rust, Tauri's Linux dependencies, or the required
Node/pnpm toolchain, run the same source gate in the pinned Linux builder:

```sh
./desktop/scripts/run-linux-builder.sh "pnpm run verify"
```

The containerized build owns only checkout-mounted files and runs as the host
UID/GID so `desktop/src-tauri/target` and downloaded sidecars remain editable.
It provides build/test tooling; it does not turn a Linux cross-build into
native Windows or macOS evidence.

To build a local Linux desktop candidate with the fixed CLI worktree embedded,
use the temporary sidecar override helper. It reads the release-pinned vendor
identity, temporarily replaces only the target sidecar, and restores that
sidecar when the build exits:

```sh
./desktop/scripts/build-with-local-cli.sh /path/to/omnideck-cli \
  "pnpm exec tauri build --bundles deb rpm --target x86_64-unknown-linux-gnu"
```

This is a local candidate workflow only; it is not release evidence until the
CLI is published and the vendor manifest is intentionally updated.

For a local Windows x64 candidate with a fixed CLI worktree, use the
containerized cross-builder:

```sh
./desktop/scripts/build-with-local-cli-windows.sh /path/to/omnideck-cli
```

The helper builds the Windows CLI in `omnideck-cli-builder:local`, builds the
unsigned GNU-target NSIS package in the pinned Windows builder, and restores
the release sidecar before returning. This is a disposable VM candidate, not
a replacement for the native Windows MSVC release build.

The `omnideck application` workflow applies the same source checks to desktop
pull requests, `main`, and tags. It also resolves the container tag once to an
immutable digest and builds the package matrix on native build runners. A
Windows ARM64 package built on Windows x64 remains a cross-build until executed
on ARM64 hardware.

## Automated security boundary

Source tests must keep the following invariants release-blocking:

- only the local `main` setup window receives the `read-only-cli` capability;
- exactly `bootstrap`, `begin_setup`, `open_app`, and `run_action` are exposed;
- Rust, not web content, owns every CLI argument;
- hosted content has no Tauri capability or command bridge;
- only the exact dynamic `http://127.0.0.1:<port>` origin remains in-app;
- external HTTP(S) navigations and new windows go to the system browser;
- non-HTTP(S), lookalike localhost, alternate-port, credentials-in-URL, IPv6,
  redirect, and subdomain bypass attempts are denied;
- malformed command payloads and malformed, oversized, truncated, or timed-out
  CLI output fail within defined bounds; and
- port collision and non-2xx readiness cannot expose an unready hosted view.

When a behavior above lacks a deterministic test, add the test before relying
on the invariant as release evidence. Do not expand production capabilities to
create a test seam.

## Release artifact contract

Every release contains ten packages and ten matching `.sha256` files:

| OS | Architecture | Package formats | Build runner | Native execution requirement |
| --- | --- | --- | --- | --- |
| Windows | x64 | NSIS | Windows x64 | Required |
| Windows | ARM64 | NSIS | Windows x64 cross-build | Required when hardware is available; otherwise explicitly blocked |
| macOS | x64 | DMG | Intel macOS | Required when Intel remains supported; otherwise explicitly build-only |
| macOS | ARM64 | DMG | Apple Silicon | Required |
| Linux | x64 | AppImage, DEB, RPM | Ubuntu x64 | AppImage smoke plus lifecycle checks for all three formats |
| Linux | ARM64 | AppImage, DEB, RPM | Ubuntu ARM64 | Required when hardware is available; otherwise explicitly blocked |

The static release contract verifies the exact filenames, checksums, file
signatures, and AppImage architectures. The tag workflow runs it on build
artifacts before the protected publication step. After publication, dispatch:

```sh
gh workflow run desktop-release-contract.yml \
  --ref main \
  -f version=v0.1.0-alpha.8
```

That workflow downloads the public assets, verifies every package's GitHub
attestation, and reruns the contract. A static contract does not inspect every
installed file or prove launch; those claims require native smoke and package
lifecycle evidence.

## Native packaged smoke

The hardware harness launches the packaged host with
`OMNIDECK_DESKTOP_SMOKE_FILE`. The production code executes only the bundled
CLI's `--version` and `--json runtime status`, then writes a proof containing
`"mutation": false`. The harness verifies the pinned CLI version/commit,
runtime schema 4, operation list, and application hash before terminating the
host.

Run it directly or through the published-release helpers documented in
[`tests/hardware`](tests/hardware/README.md). The opt-in `Native desktop package
smoke` workflow targets self-hosted real desktop sessions and never runs
untrusted pull-request code. Linux requires a real X11 or Wayland session; a
headless executable invocation is not GUI evidence.

Smoke must cover no terminal window, successful proof creation, and clean host
termination. Product-level automation should additionally cover visible hosted
UI, clipboard round trips, refresh, external browser routing, single-instance
focus, both-window close behavior, and macOS Edit-menu accelerators.

Before publishing a local candidate, run the disposable VM suite documented in
[`tests/e2e`](tests/e2e/README.md). It builds or accepts an exact package,
executes the existing packaged smoke, drives the live Tauri setup WebView
against the frozen exact-copy mockup, opens the production-pinned hosted image,
and covers returning, Doctor, resume, update, uninstall, and reinstall behavior.
Its per-run folder is the local regression record; it is not provenance for an
artifact that has not yet been published.

## Setup, failure, and lifecycle coverage

The setup state-machine suite must cover pristine first run, already-ready
runtime, partial setup, restart required, permission cancellation, missing or
nonexecutable sidecar, nonzero exit, malformed/partial output, timeout, offline
registry, interrupted download and recovery, digest mismatch, port collision,
readiness failure/recovery, close-during-action, and restart after interruption.
Pair state assertions with frozen parity text/DOM assertions.

Package lifecycle testing covers clean install, reinstall, uninstall, and
reinstall-after-uninstall. It records installed files, launchers, shortcuts,
receipts, processes, mounted images, preserved app data, and residue. Ordinary
uninstall must not remove unrelated Podman/container state. The destructive lab
reset is not an uninstaller test.

## Manual requirements

The checked-in procedures cover:

- browser download, checksum, attestation, and unsigned-package trust UX;
- clean-machine installation, elevation cancellation/approval, setup parity,
  Windows restart/resume, and hosted readiness;
- clipboard, refresh, exact-origin navigation, external links, denied schemes,
  single-instance focus, clean exit, and returning-user behavior;
- resume, update, doctor, interruption, network, port, runtime, uninstall, and
  reinstall scenarios; and
- theme, DPI, multi-monitor, accessibility, menus, icons, desktop integration,
  performance, sleep/wake, and platform fit.

Use the evidence record in [`tests/manual/README.md`](tests/manual/README.md).
For the disposable VM lab's ownership lease, viewer, and cleanup commands,
use [`tests/manual/local-vm-lab.md`](tests/manual/local-vm-lab.md).
Real published artifacts are required for trust and package UX evidence.

## Promotion gates

Promotion uses evidence for the exact commit and immutable published assets. A
new channel is a new tag and build; never move a tag or replace release assets.

### Alpha

An alpha requires:

- source checks green on the exact commit;
- tag/version/release-note consistency and the tag commit on `main`;
- all six sidecars and SBOMs matching the pinned vendor manifest;
- all ten packages built and passing the pre-publication release contract;
- immutable container digest, checksums, and provenance generated;
- the published-release contract green after publication;
- full clean-machine first-run and hosted-app manual evidence on Windows x64,
  macOS ARM64, and Linux x64; and
- native packaged smoke for every remaining published architecture that has
  available hardware, with unavailable targets explicitly recorded as blocked.

Unsigned alpha warnings are acceptable only when documented and distinguished
from corruption or launch failure. A post-publication failure does not mutate
the alpha; it makes that alpha unqualified for later promotion.

### Beta

A beta requires every alpha gate plus all available supported architectures,
Linux AppImage/DEB/RPM lifecycle coverage, recovery scenarios, visual/platform
fit, and no unowned blocked item on a primary platform.

### Release candidate

An RC requires every beta gate plus upgrade/rollback from the supported prior
desktop release, persistent-data preservation, accessibility review,
sleep/wake/network-transition checks, and documented performance/package-size
baselines. No blocker or high-severity defect may remain open.

### Stable

A stable release requires a selected RC with complete evidence on every
officially supported OS/architecture/package format, signed/notarized package
policy resolved, release notes with upgrade behavior and known limitations, and
no unresolved release blocker. Any source change requires a new RC.

## Evidence and retention

Automated evidence consists of immutable Actions run URLs, JSON reports,
checksums, SBOMs, and attestations. Generated local reports belong beneath
`artifacts/` and are not committed. Native/manual evidence is attached to the
candidate's promotion record. The protected `release` environment is the
pre-publication review point; approval means all applicable pre-publication
evidence has been checked.
