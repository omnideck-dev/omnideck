# Local VM Desktop end-to-end suite

This suite runs the real packaged Tauri desktop in the disposable local VM lab.
It does not use a dev server, a browser substitute, or a mocked host bridge.
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
exactly matches the installed WebView2 runtime, and creates/removes the Windows
interactive driver task. That task also starts Podman's WSL networking helper
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

## Evidence and disk cleanup

Everything unique to a run is under exactly one directory:

```text
$OMNIDECK_VM_LAB_DIR/artifacts/desktop-e2e/<run>-<lane>/
```

It contains `run.json`, package checksum/identity, guest inventories, live DOM
states, VM-console screenshots, host/driver logs, packaged smoke proof,
`summary.json`, `junit.xml`, `manual-remainder.json`, and the exact golden-image
prerequisite contract. The package bytes are not duplicated into evidence; the
SHA-256 identifies the exact input while the normal Tauri target directory
remains a reusable build cache.

The lab archives an overlay on each reset. A successful run deletes only the
disk and Windows TPM archives that appeared during that run. A failed or
`--keep-vm` run retains those exact paths in `discarded-created.txt`. Purge the
entire run and its retained disposable state with:

```sh
pnpm run test:vm-e2e:purge -- \
  "$OMNIDECK_VM_LAB_DIR/artifacts/desktop-e2e/<run>-<lane>"
```

The purge command accepts only a marked direct child of `artifacts/desktop-e2e`,
shows disk usage, and requires the exact run-directory name.

A published qualification groups every lane folder, release contract,
provenance log, aggregate `summary.json`, and aggregate `junit.xml` under:

```text
$OMNIDECK_VM_LAB_DIR/artifacts/desktop-release/<run>/
```

Downloaded package bytes are deleted automatically at the end, including on
failure; pass `--keep-downloads` only when debugging. Purge one qualification
and any retained disposable overlays named by its nested lane manifests with:

```sh
pnpm run test:release-e2e:purge -- \
  "$OMNIDECK_VM_LAB_DIR/artifacts/desktop-release/<run>"
```

## Manual remainder

`manual-remainder.json` is copied into every native lane with status `not-run`.
It routes a person or testing agent to the checked-in procedures for normal
browser download warnings, native macOS Gatekeeper/permission behavior,
external-browser and clipboard integration, subjective visuals/accessibility,
and timing-dependent interruption tests. Windows SmartScreen, UAC,
restart-now, and RunOnce are no longer classified as manual. Remaining checks
stay explicit `not-run`/`blocked` until their own evidence exists.

Occupied-port recovery is automated on every local Linux and Windows lane. It
creates a second saved CLI instance using Desktop's persisted port, records the
live packaged WebView showing `Choosing another private address…` and
`Port <number> is already in use`, proves no user action is exposed, and then
verifies that the running instance and persisted configuration use a different
port. The fixture and all evidence remain inside that lane's single purgeable
run directory.

Fast source checks for the harness are:

```sh
bash -n tests/e2e/run.sh tests/e2e/run-windows.sh tests/e2e/qualify-release.sh tests/e2e/linux_guest.sh
python3 -m unittest tests/e2e/test_webdriver_client.py
```
