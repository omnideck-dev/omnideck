# Native packaged desktop smoke

This harness launches a packaged desktop executable on a real operating-system
session. The production host performs only `--version` and
`--json runtime status` through its bundled sidecar, writes a proof with
`"mutation": false`, and remains open until the harness terminates it.

The validator checks the pinned CLI version and commit, runtime schema 4, the
exact read-only operations, and the application hash. Add `--require-ready` or
`-RequireReady` when the machine is expected to have a ready Podman runtime.

```sh
bash ./desktop/tests/hardware/run.sh \
  --application /path/to/omnideck \
  --require-ready
```

```powershell
./desktop/tests/hardware/run.ps1 `
  -Application C:\path\to\omnideck.exe `
  -RequireReady
```

The published-release helpers can download the appropriate artifact and invoke
the harness with `--smoke` or `-Smoke`:

```sh
./desktop/scripts/release-test/linux.sh --release v0.1.0-alpha.8 --scenario keep --smoke
./desktop/scripts/release-test/macos.sh --release v0.1.0-alpha.8 --scenario keep --smoke
```

```powershell
./desktop/scripts/release-test/windows.ps1 `
  -Release v0.1.0-alpha.8 -Scenario Keep -Smoke
```

Linux requires an actual X11 or Wayland session. macOS runs the application
from the mounted DMG. Windows silently installs the NSIS package first. These
are package/sidecar smoke tests, not clean-machine setup or visual signoff.
The Windows package remains installed; restore the dedicated runner snapshot or
perform the separately verified uninstall procedure after the job.

The `Native desktop package smoke` workflow is opt-in and uses dedicated
self-hosted machines. A missing runner or an unexecuted target is blocked
coverage, never a pass. Generated evidence belongs under
`artifacts/desktop-hardware/` and is not committed.
