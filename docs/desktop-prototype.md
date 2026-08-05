# Desktop prototype

The desktop prototype makes omnideck behave like a normal installed
application. It owns the first-run experience, prepares an isolated local
runtime, downloads the fixed omnideck image selected for the release, and opens
the interface in an application window.

The prototype targets:

- Apple Silicon macOS
- x64 Windows 11
- x64 Linux distributions through AppImage, DEB, and RPM packages

The user is never asked to run a terminal command or understand the underlying
runtime. A fresh setup can show an operating-system password or permission
prompt because macOS and Linux require approval before installing system
components. Windows enables WSL 2 through a normal UAC prompt when necessary
and resumes setup after the required restart.

Agent Dash runs entirely in the setup renderer while the runtime and application
image are prepared. It has no network or runtime dependency and never blocks
setup progress or diagnostic errors.

## Setup lifecycle

The application records setup progress in `setup-state.json` under its
application-data directory. The record includes the application version and
exact pinned image digest.

- No setup record or usable legacy environment opens the first-time Welcome
  screen.
- An in-progress record resumes setup automatically and reuses completed
  downloads, image layers, and persistent volumes when possible.
- A completed record with the same pinned image opens the application directly,
  even when only the desktop wrapper version changed.
- A completed record with a different pinned image runs the update flow.
- A completed but unhealthy environment opens diagnostics.

Diagnostics are populated from the checks that ran during that launch or setup
attempt. Checks blocked by an earlier failure remain `Not checked`; successful
setup does not show the diagnostic checklist.

The guarded scripts in `desktop/scripts/release-test/` download a published
release and launch isolated first-run, interrupted, update, returning, and
doctor scenarios on macOS, Linux, or Windows.

## Runtime topology

On macOS and Windows, the first-run flow downloads the pinned official Podman
installer, verifies it, and creates a private machine named
`omnideck-runtime`. On Linux, it uses native rootless Podman and offers to
install it through the distribution package manager and a graphical Polkit
prompt when needed.

Linux deliberately does not run a Podman machine. Containers are already
native Linux processes there, so adding a nested VM would increase first-run
time, memory use, and failure modes without improving application consistency.
All three platforms still use the same versioned omnideck image and application
lifecycle. A single pinned multi-architecture image digest selects amd64 for
Windows and Linux x64, and arm64 for Apple Silicon macOS.

The desktop state, engine configuration, volumes, and container are separate
from a developer's normal Podman state. The setup screen does not expose
Podman, containers, virtual machines, or terminal commands to the user.

## Run from source

Install the desktop dependencies:

```bash
cd desktop
npm ci
```

Source builds require Node.js 22.12 or newer.

Start the development application:

```bash
npm start
```

The development build uses a separate private runtime and storage area under
Electron's omnideck application-data directory. It does not reuse containers
or volumes created by the standalone CLI. Source mode can pull the development
image when no release manifest is present; packaged builds cannot use this
fallback.

## Build local installers

Packaged builds require `build/runtime/image-manifest.json`. Generate it from
the immutable digest of the published multi-architecture container release
named by `desktop/container-version.txt`:

```bash
node scripts/prepare-runtime-image.cjs \
  ghcr.io/omnideck-dev/omnideck@sha256:<digest>
```

Then run the matching command on each operating system:

```bash
npm run dist:linux:container
npm run dist:mac -- --arm64
npm run dist:windows -- --x64
```

Installers are written to `desktop/dist/`.

The Linux command uses an ephemeral Node container and Docker-managed dependency
volumes, so DEB and RPM build tools are not installed on the host. macOS and
Windows installers are built natively on their matching operating systems or on
the matching GitHub-hosted runners.

Unsigned installers are suitable for testing on computers you control:

- On macOS, use Open from the Finder context menu when Gatekeeper warns about
  an unidentified developer.
- On Windows, use More info and Run anyway when SmartScreen warns about an
  unknown publisher.
- Linux does not have an equivalent mandatory platform signing gate, although
  package repositories may impose their own policy.

External testers should receive signed builds. macOS builds need a Developer
ID Application certificate and Apple notarization. Windows builds need an
Authenticode certificate with enough reputation to avoid persistent
SmartScreen warnings.

## GitHub builds and releases

The application workflow can be run manually to produce test artifacts for all
three operating systems. Pushing a `vX.Y.Z` version tag publishes only the
matching desktop release. It resolves the immutable digest of the independent
container release selected in `desktop/container-version.txt`, embeds both that
container version and digest in each installer, and publishes the installers in
the omnideck repository. On first setup, packaged applications pull the pinned
digest from GHCR; later launches reuse the local image.

Container releases have their own version line. Run the **Release container**
workflow from `main` with a plain `X.Y.Z` version. It promotes the tested
`main-<commit>` multi-architecture image to that GHCR tag without creating a Git
tag or publishing desktop installers. An existing version can never be moved to
a different digest. Update `desktop/container-version.txt` only when a desktop
release should ship a different container release.

The workflow accepts these optional repository secrets:

| Secret | Purpose |
| --- | --- |
| `DESKTOP_MAC_CSC_LINK` | Base64 or URL for the macOS signing certificate |
| `DESKTOP_MAC_CSC_KEY_PASSWORD` | macOS signing-certificate password |
| `DESKTOP_WINDOWS_CSC_LINK` | Base64 or URL for the Windows signing certificate |
| `DESKTOP_WINDOWS_CSC_KEY_PASSWORD` | Windows signing-certificate password |
| `DESKTOP_APPLE_ID` | Apple account used for notarization |
| `DESKTOP_APPLE_APP_SPECIFIC_PASSWORD` | App-specific Apple password |
| `DESKTOP_APPLE_TEAM_ID` | Apple developer team |

The macOS and Windows jobs remain unsigned when the matching credentials are
not present, which keeps local and internal prototype builds possible.

## Prototype boundaries

The prototype intentionally orchestrates the small runtime surface directly.
This makes the first cross-platform build independent of terminal-oriented CLI
output. After the UX and platform packaging are proven, the lifecycle code
should move behind the shared Go workflow layer so the CLI and desktop app
cannot drift.

The runtime installer is pinned to Podman 6.0.2 and verified by SHA-256 before
execution. The application image is tied to the independent version in
`desktop/container-version.txt` and an immutable multi-architecture SHA-256
digest. The desktop `package.json` version identifies the host application;
the two versions do not have to match. Packaged builds never pull `latest`.
Production releases should update each pin deliberately, retain the checks,
and include complete third-party notices.

The local app is published only on a loopback port. It uses
`127.0.0.1:2337` when available and automatically remembers another free port
when that port is already occupied. The container continues running when the
window closes so scheduled work can continue.

The prototype replaces an older application container without replacing the
persistent user volumes. It does not auto-update the host application yet. Add
updates and rollback after native installation and signed release artifacts are
proven on the three test computers.
