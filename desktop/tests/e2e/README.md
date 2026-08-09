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
- namespaced Linux container/volume isolation and cleanup;
- DEB/RPM uninstall/reinstall without removing runtime data; and
- NSIS silent uninstall/reinstall while preserving user/runtime data.

The default checkpoint is `podman-ready`. The CLI VM E2E suite owns pristine
Podman/WSL installation behavior; this Desktop lane starts from the reusable
runtime checkpoint so it can exercise the complete desktop-owned lifecycle
reliably on every pre-release run. Linux accepts `--baseline clean` and drives
the graphical permission prompt. The automated Windows lane intentionally
rejects `clean`: real UAC cancellation/approval, restart-now, and RunOnce
reopen remain in `tests/manual/clean-first-run.md` because a WebDriver session
cannot survive the secure-desktop/reboot boundary without changing product
behavior.

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

To revise a golden, start from `clean`, install only the checkpoint items in
the contract, initialize Podman, run each listed verification command, shut
the guest down cleanly, and create a new named checkpoint such as
`desktop-e2e-v1`. Do not replace `clean`. Prove the new checkpoint before
adopting it:

```sh
pnpm run test:vm-e2e -- --vm appimage --baseline desktop-e2e-v1
pnpm run test:vm-e2e -- --vm windows --baseline desktop-e2e-v1
```

Once both lanes pass, set `OMNIDECK_DESKTOP_VM_E2E_BASELINE` or continue to
pass `--baseline`; `podman-ready` remains the portable default.

## Run before publication

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

## Manual remainder

`manual-remainder.json` is copied into every run with status `not-run`. It
routes a person or testing agent to the checked-in procedures for published
trust UI, Windows UAC/restart-now, external-browser and clipboard integration,
subjective visuals/accessibility, and timing-dependent interruption tests.
Those checks stay explicit `not-run`/`blocked` until their own evidence exists.

Fast source checks for the harness are:

```sh
bash -n tests/e2e/run.sh tests/e2e/run-windows.sh tests/e2e/linux_guest.sh
python3 -m unittest tests/e2e/test_webdriver_client.py
```
