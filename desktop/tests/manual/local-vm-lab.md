# Local VM lab controls

Use the external disposable VM lab for desktop manual work. The lab path is
machine-specific and must not be committed to repository documentation.

## Inventory and ownership

```sh
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
test -x "$OMNIDECK_VM_LAB_DIR/lab.sh"
cd "$OMNIDECK_VM_LAB_DIR"
./lab.sh status
```

Acquire a lane lease before starting a guest. QEMU inherits the lock
descriptor, so the lease remains held while the guest is running:

```sh
flock -n /tmp/omnideck-desktop-windows-lease.lock bash -c \
  'cd "$OMNIDECK_VM_LAB_DIR" && ./lab.sh start windows && ./lab.sh wait windows && ./lab.sh verify windows'
fuser -v /tmp/omnideck-desktop-windows-lease.lock
```

If the lease is held, inspect its owner and do not stop, reset, or snapshot
that guest. Keep the Windows guest stopped when it is reserved for another
desktop run.

## Reusable guest checkpoints

Treat each `*-clean.qcow2` image as the immutable fresh baseline. Use
named checkpoints for expensive setup states; a checkpoint includes the guest
disk plus UEFI state and, for Windows, TPM state:

```sh
cd "$OMNIDECK_VM_LAB_DIR"
./lab.sh snapshots windows
./lab.sh reset windows clean
./lab.sh reset windows wsl-ready
./lab.sh reset windows podman-ready
```

Create a checkpoint only after the guest is in the intended state and has
been cleanly powered off. The command stops the guest if it is running and
refuses to overwrite an existing checkpoint:

```sh
./lab.sh snapshot windows wsl-ready
./lab.sh snapshot windows podman-ready
```

Use lowercase names containing only letters, numbers, `.`, `_`, and `-`.
`clean` is reserved for the original golden state. Do not replace the clean
golden image with a configured state; recreate a named checkpoint when the
state needs to change. The legacy `./lab.sh snapshot VM` form replaces the
clean image and is only for intentionally creating or rebuilding a golden
image.

The Desktop lane's versioned install and verification contract is
[`../e2e/golden-prerequisites.json`](../e2e/golden-prerequisites.json). Put
stable graphical-session, SSH, WebKit/WebView2, and Podman prerequisites in a
named checkpoint. Keep the exact Tauri driver, matching EdgeDriver, candidate,
driver task, and evidence per-run; the harness owns those and removes them with
the disposable state. After rebuilding a checkpoint, run both the AppImage and
Windows lanes against its explicit name before making it the local default.

## Automated package journeys

The native packaged behavior that can be controlled deterministically now runs
through [`../e2e`](../e2e/README.md). That suite owns the VM lease, reset,
package build/install, packaged smoke, live setup DOM/copy, hosted open,
returning/Doctor/resume/update scenarios, package lifecycle, compact evidence,
and safe overlay/TPM cleanup.

Use it before opening a viewer for the remaining manual checks:

```sh
cd /path/to/omnideck/desktop
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
export OMNIDECK_CLI_WORKTREE=/path/to/omnideck-cli
pnpm run test:vm-e2e -- --vm appimage
pnpm run test:vm-e2e -- --vm windows
```

## Manual Windows desktop remainder

The graphical viewer remains required for secure-desktop cancellation/approval,
the restart-now RunOnce reopen path, visible terminal behavior, trust warnings,
and subjective visual evidence. The automated suite copies
`manual-remainder.json` into its run folder and does not represent these steps
as a pass:

```sh
cd "$OMNIDECK_VM_LAB_DIR"
./lab.sh start windows
./lab.sh wait windows
./lab.sh verify windows
./lab.sh viewer windows
# Perform desktop/tests/manual/clean-first-run.md in the viewer.
# Record screenshots, inventories, exact artifact checksum, and result.
./lab.sh stop windows
./lab.sh reset windows
./lab.sh status windows
```

Use the same explicit sequence for a recovery run, substituting
`recovery-lifecycle.md` for the first-run procedure. Do not run the destructive
host reset against a development machine.

## Repeatable non-visual checks

Build a local Linux desktop candidate with the fixed CLI worktree before
copying it to the guest:

```sh
cd /path/to/omnideck
./desktop/scripts/build-with-local-cli.sh /path/to/omnideck-cli \
  "pnpm exec tauri build --bundles appimage --target x86_64-unknown-linux-gnu"
```

The helper builds Go in the pinned CLI container, temporarily stages the local
Linux sidecar, builds the AppImage in the pinned desktop container, and restores
the release sidecar before returning. The resulting AppImage is under
`desktop/src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/appimage/`.

Build the local Windows candidate with the same CLI worktree:

```sh
cd /path/to/omnideck
./desktop/scripts/build-with-local-cli-windows.sh /path/to/omnideck-cli
sha256sum desktop/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis/*-setup.exe
```

Copy that installer into the disposable Windows guest, install it with the
default current-user options, and verify the installed
`AppData\\Local\\omnideck\\omnideck-cli.exe` hash before setup. The local GNU
package is intentionally for lab testing; native Windows CI produces the
release MSVC package.

The CLI worktree contains the reusable containerized lifecycle helper:

```sh
cd /path/to/omnideck-cli
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
OMNIDECK_VM_LAB_VM=atomic \
OMNIDECK_HARDWARE_ENGINE=podman \
./tests/manual/run-local-hardware.sh
```

It builds Go inside `omnideck-cli-builder:local`, runs the Podman lifecycle in
an isolated Linux guest, and stores checksum/log evidence under the external
lab. It does not replace the desktop viewer procedure above.

## Evidence and cleanup

Record the source commit, package checksum, guest OS/version, display server,
Podman/runtime baseline, exact commands, timestamps, result, screenshots/logs,
and final inventory. Redact credentials and personal paths.

Only after evidence is copied out, clean the disposable overlay:

```sh
cd "$OMNIDECK_VM_LAB_DIR"
./lab.sh stop windows
./lab.sh reset windows
./lab.sh status windows
```
