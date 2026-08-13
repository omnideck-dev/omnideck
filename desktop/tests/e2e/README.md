# Local VM Desktop end-to-end suite

This suite runs the real packaged Tauri desktop in the disposable local VM lab.
It does not use a dev server, a browser substitute, or a mocked host bridge.
Each runner acquires the lab's per-guest lease before any reset, start, console,
or copy operation, so concurrent suites cannot mutate the same guest.
The default pre-release path builds the current checkout with the same
AppImage/DEB/RPM/NSIS packaging commands used by the release build and embeds
the selected local CLI worktree. `--artifact PATH` runs the same suite against
an exact prebuilt or downloaded package instead. Every report records the
package SHA-256.

The setup journey uses the native Tauri WebDriver on Linux and Windows. It
reads the live packaged WebView and compares visible title/detail/action text
to `src-tauri/setup-parity.json`. That contract must exactly equal the frozen
Electron UX mockup before the driver starts. The existing source test also
keeps the full HTML, CSS, JavaScript, Agent Dash, DOM, and parity JSON
byte-for-byte equal to the mockup.

The controller is maintained in the standalone `omnideck-vm-lab` repository,
not this application repository. Install controller 2.x into the external lab
before running these consumers.

## Automated coverage

Each lane performs as much deterministic native automation as its operating
system exposes:

- package SHA-256 verification and native AppImage launch, DEB/RPM install, or
  current-user NSIS install;
- read-only packaged smoke through the bundled CLI (`--version` and
  `--json runtime status`), with the pinned CLI identity and schema checked;
- the real Welcome action, setup progress, production-pinned runtime image,
  Ready action, dynamic loopback hosted window, and stable hosted-app root;
- live exact-copy and DOM evidence from the packaged setup WebView;
- returning-user direct open, missing-container Doctor/retry, interrupted setup
  resume, and candidate update reconciliation;
- a second saved installation occupying Desktop's persisted port, the exact
  inline recovery wording, no-action automatic retry, and successful launch on
  a newly persisted port;
- a real Custom App installed into the existing Desktop home volume, rendered
  in the packaged platform WebView, invoked through the same-origin SDK bridge
  and Python action runner, then invoked again after restarting the Tauri app;
- profile export through the real Agents UI, with the hosted URL held stable
  while the native webview writes the expected file into the guest Downloads
  folder, followed by filename, JSON pack, version, payload, and visible
  completion-toast validation;
- profile import through the real native-driver file-input command, using that
  guest-local downloaded file and proving both the created profile and success
  notification;
- artifact download from the real Artifacts preview, with guest filesystem
  contents and the native completion toast verified;
- Ctrl/Cmd keyboard and standardized mouse-wheel events through the packaged
  desktop-only webview zoom control, plus trusted OS-level keyboard and wheel
  input in the Linux guests, proving each path updates the rendered page zoom;
  and
- deterministic test-only update discovery, defer, skip, event delivery, and
  the exact frozen hosted bridge surface (without replacing the runtime image);
- namespaced Linux container/volume isolation and cleanup;
- DEB/RPM uninstall/reinstall without removing runtime data; and
- NSIS silent uninstall/reinstall while preserving user/runtime data.

The Windows `clean` lane also automates the boundaries that WebDriver cannot
cross by itself:

- Windows Attachment Manager internet-zone metadata and either the real
  SmartScreen warning/bypass or the trusted no-warning installer path;
- real secure-desktop UAC cancellation, exact in-app cancellation copy,
  retry, and approval through the QEMU console;
- the exact Restart now/Restart later interface, selection of Restart now, a
  verified SSH disconnect, and a changed Windows boot identity; and
- console-driven sign-in, consumption of the product's real RunOnce value,
  interactive app reopening, persisted setup state, post-reboot elevation, and
  completion.

On Linux, the harness automatically selects the versioned
`recommendedBaseline` from `golden-prerequisites.json` when that checkpoint is
present in the local lab, and otherwise falls back to the portable
`podman-ready` checkpoint. Silverblue uses its `clean` atomic deployment and
the x64 AppImage. Its unattended smoke launches the AppImage itself; its
attended WebDriver journeys extract and hash-check the byte-identical shipped
`omnideck` and `omnideck-cli` binaries, then run them outside the AppDir so they
bind to Silverblue's native WebKitGTK. This avoids combining the AppImage's
Ubuntu WebKit libraries with Fedora's WebDriver while still proving both the
package loader and the distro-native Tauri behavior. Windows defaults to
`podman-ready` for a faster development
loop, while `--baseline clean` owns the full UAC/restart/RunOnce path. The
published-release orchestrator always selects `clean` for Windows. Linux also
accepts `--baseline clean` and drives its graphical permission prompt.

The production-pinned runtime image is used by default. There is no tiny
fixture image in the full Desktop journey. This makes the hosted proof a check
of the same application image the package declares, at the cost of a larger
first pull inside the disposable overlay.

The full lane pays the expensive costs once: one guest reset, one candidate
build/install, and one production image pull. Lifecycle journeys intentionally
open fresh desktop sessions because they prove returning, repair, resume,
update, and port-recovery behavior, but they reuse the same run-scoped
container volumes. The Custom App check also reuses that final healthy runtime;
one driver process opens two application sessions only to prove the app and its
action survive a real Tauri restart.

## Golden-image automation prerequisites

The versioned checkpoint contract is
[`golden-prerequisites.json`](golden-prerequisites.json). Bake the stable guest
dependencies into a reusable checkpoint: a graphical `tester` session,
OpenSSH, Podman/runtime initialization, and WebKitWebDriver on Linux; an
interactive `tester` Explorer session, OpenSSH, WebView2 Evergreen, and the
initialized Podman WSL machine with working registry DNS on Windows. The lane
verifies these capabilities and records the contract with every run.

Keep version-coupled tooling out of the golden image. The harness builds and
stages locked `tauri-driver` 2.0.6 for every run, downloads the EdgeDriver that
matches the active EdgeWebView client's registry `pv`, rejects a driver with a
different major version, and creates/removes the Windows interactive driver
task. This avoids selecting an inactive update directory left beside the
runtime Tauri actually loads. The active value is checked again after a real
reboot so an Evergreen update refreshes the staged driver before the next
WebDriver session. That task also starts Podman's WSL networking helper
inside the logged-in desktop session and proves registry DNS before exposing
the driver. A golden image can therefore be refreshed without silently
changing what drives the candidate.

To revise a golden, start from `clean` or the preceding named checkpoint,
install only the checkpoint items in the contract, initialize Podman, run each
listed verification command, shut the guest down cleanly, and create a new
named checkpoint such as `desktop-e2e-v2`. Do not replace `clean`. Prove the
new checkpoint before adopting it:

```sh
pnpm run test:vm-e2e -- --vm appimage --baseline desktop-e2e-v2
pnpm run test:vm-e2e -- --vm windows --baseline podman-ready
```

`desktop-e2e-v2` masks `systemd-networkd-wait-online.service` only after
proving that NetworkManager owns the guest link and networkd reports it as
unmanaged. It also bakes `WebKitWebDriver` into the checkpoint. A verified lab
with that named checkpoint uses it automatically; `podman-ready` remains the
portable fallback. `--baseline` and `OMNIDECK_DESKTOP_VM_E2E_BASELINE` always
override automatic selection.

## Qualify the latest published release with one command

From `desktop/`, with every selected disposable guest stopped:

```sh
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
pnpm run test:release-e2e -- --release latest --yes
```

`latest` includes published prereleases. The command downloads the exact
public release assets, verifies all ten packages and their checksums, validates
package format and architecture, verifies GitHub attestations, reads the
bundled CLI identity from the release tag, and runs these local x64 lanes
sequentially:

| Lane | Guest | Public package | Native journey |
|---|---|---|---|
| `appimage` | Ubuntu 24.04 GNOME | AppImage | full, including occupied-port recovery |
| `deb` | Debian 13 GNOME | DEB | full, occupied-port recovery, and install/uninstall/reinstall |
| `rpm` | Fedora 44 Workstation | RPM | full, occupied-port recovery, and install/uninstall/reinstall |
| `atomic` | Fedora Silverblue 44 | AppImage | packaged smoke plus full byte-identical native-binary journey, including occupied-port recovery |
| `windows` | Windows 11 Pro 25H2 clean | NSIS | trust, UAC, reboot, RunOnce, occupied-port recovery, and full lifecycle |

The same artifact contract statically proves the published macOS and ARM64
packages; it labels them as static coverage, never as native execution. If the
dedicated self-hosted Windows ARM64, Linux ARM64, Intel macOS, and Apple Silicon
machines are online, add `--remote-native`. The command dispatches the existing
`desktop-hardware.yml` lanes, waits for them, downloads their evidence, and
requires them to pass. Without those machines, the corresponding native lanes
remain explicit `not-run` entries in `summary.json`.

Use `--lanes appimage,windows` for a shorter subset. A selected guest that is
already running blocks the qualification before packages are downloaded; the
harness never stops or resets a guest it does not own.

Add `--cross-distro-smoke` to reuse the downloaded AppImage, DEB, and RPM in
the launch-only compatibility matrix described below. Its aggregate result is
included in the qualification summary. The flag is opt-in because the extra
cells each boot and reset a disposable guest; Flatpak is not included because
the release does not publish a Flatpak bundle.

## Run a development candidate before publication

From `desktop/`:

```sh
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
export OMNIDECK_CLI_WORKTREE=/path/to/omnideck-cli
pnpm run test:vm-e2e -- --vm appimage
pnpm run test:vm-e2e -- --vm windows
```

Additional Linux package lanes:

```sh
pnpm run test:vm-e2e -- --vm deb
pnpm run test:vm-e2e -- --vm rpm
pnpm run test:vm-e2e -- --vm atomic
```

Run an exact already-built package without rebuilding it:

```sh
pnpm run test:vm-e2e -- --vm appimage --artifact /absolute/path/candidate.AppImage
pnpm run test:vm-e2e -- --vm windows --artifact /absolute/path/candidate-setup.exe
```

The selected guest must be stopped. The harness acquires the CLI and Desktop
lane leases, asks for the guest name before resetting, restores the clean
golden afterward, and refuses to treat a manual item as an automated pass.
Pass `--yes` only in trusted local automation. `--keep-vm` retains a stopped
debug guest and its exact discarded-state manifest.

## Cross-distro package-open smoke matrix

The full lanes above intentionally pair each installable package with its
native package manager. Use the smaller smoke runner to answer the separate
compatibility question: can these exact package bytes open on another distro
and complete the bundled CLI's read-only `--version` and runtime-status proof?
For example, `appimage` selects the Ubuntu guest even when the artifact is an
RPM:

```sh
pnpm run test:vm-smoke -- \
  --vm appimage \
  --artifact /absolute/path/omnideck-0.1.0-1.x86_64.rpm
```

Run every non-native combination for the artifacts you supply with:

```sh
pnpm run test:vm-smoke-matrix -- \
  --appimage /absolute/path/omnideck_0.1.0_amd64.AppImage \
  --deb /absolute/path/omnideck_0.1.0_amd64.deb \
  --rpm /absolute/path/omnideck-0.1.0-1.x86_64.rpm
```

The default guests are Ubuntu (`appimage`), Debian (`deb`), Fedora (`rpm`), and
Silverblue (`atomic`). Native cells already covered by the full lanes are
skipped unless `--include-native` is passed. On a matching distro the smoke
uses APT or DNF to install the package. On a foreign distro it extracts the
DEB or RPM payload into the disposable run directory and launches the shipped
binary from there; this proves payload compatibility, not support for using a
foreign system package manager.

Flatpak is supported by the smoke harness when a bundle is supplied:

```sh
pnpm run test:vm-smoke-matrix -- \
  --flatpak /absolute/path/dev.omnideck.desktop.flatpak
```

The current release contract does not publish a Flatpak, so Flatpak cells are
not inferred or reported as passing unless an exact `.flatpak` bundle is
provided. The harness installs that bundle for the disposable user, launches
it through `flatpak run`, and requires the same packaged smoke proof.

## Evidence and disk cleanup

Everything unique to a run is under exactly one directory:

```text
$OMNIDECK_VM_LAB_DIR/artifacts/desktop/e2e/<run>-<lane>/
```

It contains `run.json`, package checksum/identity, guest inventories, live DOM
states, VM-console screenshots, host/driver logs, downloaded-file validation,
host-boundary download/import reports, packaged smoke proof,
`summary.json`, `junit.xml`, `manual-remainder.json`, and the exact golden-image
prerequisite contract. The package bytes are not duplicated into evidence; the
SHA-256 identifies the exact input while the normal Tauri target directory
remains a reusable build cache.

The lab archives reset state inside one transaction. Successful transaction
state is deleted immediately. Failed or `--keep-vm` state and compact evidence
expire after 48 hours unless explicitly pinned. Purge a marked run with:

```sh
pnpm run test:vm-e2e:purge -- \
  "$OMNIDECK_VM_LAB_DIR/artifacts/desktop/e2e/<run>-<lane>"
```

The purge command delegates validation and deletion to `lab.sh runs purge`.

Single cross-distro smokes are stored under `artifacts/desktop/package-smoke`;
aggregate runs are stored under `artifacts/desktop/smoke-matrix`, with one
evidence folder per guest/package cell plus aggregate JSON and JUnit reports.
Purge either marked run and its retained overlays with:

```sh
pnpm run test:vm-smoke:purge -- \
  "$OMNIDECK_VM_LAB_DIR/artifacts/desktop/smoke-matrix/<run>"
```

A published qualification groups every lane folder, release contract,
provenance log, aggregate `summary.json`, and aggregate `junit.xml` under:

```text
$OMNIDECK_VM_LAB_DIR/artifacts/desktop/release/<run>/
```

Downloaded package bytes are deleted automatically at the end, including on
failure; pass `--keep-downloads` only when debugging. Purge one qualification
and any retained disposable overlays named by its nested lane manifests with:

```sh
pnpm run test:release-e2e:purge -- \
  "$OMNIDECK_VM_LAB_DIR/artifacts/desktop/release/<run>"
```

## Manual remainder

`manual-remainder.json` is copied into every native lane with status `not-run`.
It routes a person or testing agent to the checked-in procedures for normal
browser download warnings, native macOS Gatekeeper/permission behavior,
native file-picker presentation, external-browser and clipboard integration,
subjective visuals/accessibility, and timing-dependent interruption tests.
The data-transfer result of download/upload is automated on every Windows and
Linux lane; only the native picker's visible OS chrome remains manual. Windows
SmartScreen, UAC, restart-now, and RunOnce are no longer classified as manual.
Remaining checks stay explicit `not-run`/`blocked` until their own evidence
exists.

The boundary client deliberately speaks the same W3C protocol as the existing
setup journey and adds no production bridge or test-only host command. Current
Linux and Windows lanes use `tauri-driver`. When a macOS lab host is added, use
the WebdriverIO Tauri service's embedded driver for that lane and preserve the
same download/upload assertions and evidence fields; direct `tauri-driver`
remains a Linux/Windows transport.

Occupied-port recovery is automated on every local Linux and Windows lane. It
creates a second saved CLI instance using Desktop's persisted port, records the
live packaged WebView showing `Choosing another private address…` and
`Port <number> is already in use`, proves no user action is exposed, and then
verifies that the running instance and persisted configuration use a different
port. The fixture and all evidence remain inside that lane's single purgeable
run directory.

Fast source checks for the harness are:

```sh
bash -n tests/e2e/run.sh tests/e2e/run-windows.sh tests/e2e/qualify-release.sh \
  tests/e2e/linux_guest.sh tests/e2e/run-package-smoke.sh \
  tests/e2e/linux_package_smoke.sh tests/e2e/smoke-matrix.sh
python3 -m unittest tests/e2e/test_webdriver_client.py tests/e2e/test_host_boundary_client.py
```
