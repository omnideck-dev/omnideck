# Local VM lab controls

Use the external disposable VM lab for Desktop automation and the remaining
manual observations. The lab path is machine-specific and must not be committed.

The lab also exposes a leased, application-disposable Apple Silicon target for
exact-DMG installation and shared-container-runtime smoke:

```sh
export OMNIDECK_VM_LAB_DIR=/mnt/data/VMs/omnideck-release-lab
cd /path/to/omnideck/desktop
pnpm run test:macos-lab -- --artifact /path/to/omnideck_aarch64.dmg
```

The runner resets application state, installs the exact app as
`~/Applications/Omnideck Lab.app`, and leases cleanup back to `runtime-ready`. Podman and its VM
stay warm to fit the 8 GB host; the lane claims clean-application, not clean-OS
or snapshot coverage. Cleanup is restricted to lab-namespaced state and
resources, so a normal long-term OmniDeck installation remains usable.

## Inventory, preflight, and ownership

```sh
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
test -x "$OMNIDECK_VM_LAB_DIR/lab.sh"
cd "$OMNIDECK_VM_LAB_DIR"
./lab.sh doctor --strict
./lab.sh preflight desktop release-clean --lanes appimage,deb,rpm,atomic,windows
```

Automated suites acquire their own leases. For a manual viewer run, acquire a
lease with an explicit cleanup baseline before changing the guest:

```sh
./lab.sh lease windows desktop-manual --cleanup-baseline clean -- bash
./lab.sh start windows
./lab.sh wait windows
./lab.sh verify windows
./lab.sh viewer windows
# Perform only the remaining manual observations, then exit this shell.
exit
```

The cleanup baseline restores the guest if the shell succeeds, fails, or is
interrupted. If a lease is held, inspect its owner with `lab.sh status` and do
not stop, reset, or snapshot that guest. Do not issue another reset after the
cleanup-owning lease exits.

## Canonical automated candidate run

Run the deterministic candidate matrix before opening a viewer:

```sh
cd /path/to/omnideck/desktop
export OMNIDECK_VM_LAB_DIR=/absolute/path/to/omnideck-release-lab
export OMNIDECK_CLI_WORKTREE=/path/to/omnideck-cli
pnpm run test:vm-candidate -- --lanes appimage,deb,rpm,atomic,windows --yes
```

The matrix preflights the selected profile, builds Linux and Windows candidates
once into the lab's content-addressed cache, groups work by guest, owns every
lease/reset, and writes aggregate evidence under
`$OMNIDECK_VM_LAB_DIR/artifacts/desktop/candidate-matrix/`. Cargo, pnpm, sidecar,
driver, and package build outputs used by the candidate workflow are routed
through the lab cache instead of accumulating in the checkout.

For deliberate single-lane diagnosis:

```sh
pnpm run test:vm-e2e -- --vm appimage
pnpm run test:vm-e2e -- --vm windows
```

For launch-only cross-distribution compatibility, supply exact existing packages
to `pnpm run test:vm-smoke-matrix`; see `tests/e2e/README.md`. Do not substitute
that smoke for setup, recovery, or package-lifecycle coverage.

The clean Windows lane drives SmartScreen, secure-desktop UAC cancellation and
approval, restart-now, RunOnce reopening, setup/recovery, and package lifecycle.
Open the viewer only for items listed in `tests/e2e/manual-remainder.json`:

- normal-browser warnings and native macOS Gatekeeper;
- native macOS or another target without an automation host;
- native picker/clipboard/browser/shortcut/window integration;
- subjective visual, accessibility, DPI, multi-monitor, and platform fit; and
- live network interruption, sleep/wake, and destructive interruption timing.

## Marked manual evidence

Create the evidence record before acquiring the manual lease. This keeps every
generated report, screenshot, and log under the lab's single artifact root:

```sh
repo_root=/path/to/omnideck
source_commit="$(git -C "$repo_root" rev-parse HEAD)"
cd "$OMNIDECK_VM_LAB_DIR"
run_id="desktop-manual-$(date -u +%Y%m%dT%H%M%SZ)"
evidence_dir="$(./lab.sh artifact-path desktop manual "$run_id")"
export evidence_dir
./lab.sh evidence-init "$evidence_dir" desktop manual "$run_id" \
  "$source_commit" windows clean
./lab.sh lease windows desktop-manual "$run_id" --cleanup-baseline clean -- bash
./lab.sh start windows
./lab.sh wait windows
./lab.sh verify windows
./lab.sh viewer windows
# Write only compact manual-remainder evidence beneath $evidence_dir, then exit.
exit
./lab.sh evidence-finish "$evidence_dir" passed
```

Use `failed` instead of `passed` when an assertion fails. Record the exact
package checksum, guest/display/runtime inventory, timestamps, observations, and
final result. Do not copy candidates, raw disks, or large recordings into the
repository.

## Reusable guest checkpoints

Treat each clean image as immutable. Named checkpoints may hold stable graphical
session, WebKit/WebView2, SSH, and Podman prerequisites, but never a candidate,
exact driver, or per-run evidence. Create a checkpoint only inside a maintenance
lease and only after a clean shutdown:

```sh
cd "$OMNIDECK_VM_LAB_DIR"
./lab.sh lease windows checkpoint-maintenance --cleanup-baseline clean -- bash
./lab.sh start windows
# Prepare and verify the intended reusable prerequisite state.
./lab.sh stop windows
./lab.sh snapshot windows podman-ready-v2
exit
./lab.sh provenance capture windows podman-ready-v2
```

Validate both AppImage and Windows lanes against the explicit checkpoint before
selecting it in a shared profile. Then update the versioned lab manifest and
install that controller into the deployed lab. Because provenance binds the
complete manifest, recapture every clean or named baseline referenced by the new
manifest before running `lab.sh doctor --strict` and the exact Desktop profile
preflight. Provenance capture runs after a lease exits because it refuses a
running or leased guest. Never use snapshot or installer commands as test
cleanup.

## Evidence and generated-file cleanup

Successful reset transactions disappear immediately. Unpinned evidence and
failed state expire after 48 hours; unused content-addressed candidates and
drivers expire after seven days. Preview or apply routine cleanup from Desktop:

```sh
pnpm run test:vm-lab:cleanup
pnpm run test:vm-lab:cleanup:apply
```

For an intentional complete removal of generated artifacts, caches, and retained
reset state:

```sh
pnpm run test:vm-lab:cleanup:all
pnpm run test:vm-lab:cleanup:all:apply
```

Cleanup never targets golden images, named checkpoints, base images, automation,
or keys.
