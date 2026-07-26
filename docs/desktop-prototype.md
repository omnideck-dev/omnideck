# Desktop prototype

The desktop prototype makes OmniDeck behave like a normal installed
application. It owns the first-run experience, prepares an isolated local
runtime, imports the fixed OmniDeck image bundled with the installer, and opens
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

Agent Dash runs entirely in the setup renderer while the runtime and bundled
image are prepared. It has no network or runtime dependency and never blocks
setup progress or diagnostic errors.

## Runtime topology

On macOS and Windows, the first-run flow downloads the pinned official Podman
installer, verifies it, and creates a private machine named
`omnideck-runtime`. On Linux, it uses native rootless Podman and offers to
install it through the distribution package manager and a graphical Polkit
prompt when needed.

Linux deliberately does not run a Podman machine. Containers are already
native Linux processes there, so adding a nested VM would increase first-run
time, memory use, and failure modes without improving application consistency.
All three platforms still use the same versioned OmniDeck image and application
lifecycle. Each installer contains only the image architecture needed by its
host: amd64 for Windows and Linux x64, and arm64 for Apple Silicon macOS.

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
Electron's OmniDeck application-data directory. It does not reuse containers
or volumes created by the standalone CLI. Source mode can pull the development
image when no bundled archive is present; packaged builds cannot use this
fallback.

## Build local installers

Packaged builds require `build/runtime/omnideck-image.oci.tar` and its generated
manifest. GitHub Actions builds this archive from the same commit before
running the platform packagers. With a prepared archive, run the matching
command on each operating system:

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
three operating systems. Pushing `v0.1.0-alpha.1` builds the matching amd64 and
arm64 images, embeds them in the correct installers, and publishes a prerelease
in the OmniDeck repository. The existing container workflow also publishes the
same source revision as the multi-architecture
`ghcr.io/omnideck-dev/omnideck:0.1.0-alpha.1` image for CLI users. Packaged
applications continue to import their embedded image and do not depend on GHCR.

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
execution. The application image is tied to the `package.json` version, checked
before import, and never pulled from `latest` in a packaged build. Production
releases should update each pin deliberately, retain the checks, and include
complete third-party notices.

The local app is published only on a loopback port. It uses
`127.0.0.1:2337` when available and automatically remembers another free port
when that port is already occupied. The container continues running when the
window closes so scheduled work can continue.

The prototype replaces an older application container without replacing the
persistent user volumes. It does not auto-update the host application yet. Add
updates and rollback after native installation and signed release artifacts are
proven on the three test computers.
