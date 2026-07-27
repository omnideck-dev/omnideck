# Desktop release scenario testing

These scripts download a published desktop release, prepare an isolated test
profile, and launch the real packaged application:

- `linux.sh`
- `macos.sh`
- `windows.ps1`

They require an authenticated [GitHub CLI](https://cli.github.com/) session.
The default `keep` scenario does not delete anything. Use `--release choose` to
pick from recent releases or pass a tag such as `--release v0.1.0-alpha.4`.
The Linux helper caches an extracted AppImage so FUSE is not required.
The isolated resource namespace was introduced in `v0.1.0-alpha.4`, so the
helpers refuse older releases rather than risk touching a normal environment.

## Scenarios

| Scenario | What it exercises |
| --- | --- |
| `keep` | Launch without changing the selected test profile |
| `first-run` | Remove the isolated test container, machine, volumes, and app data |
| `resume` | Preserve cached work and volumes but simulate an interrupted setup |
| `update` | Preserve a completed environment but make its pinned image look older |
| `doctor` | Preserve completed state and volumes but remove the app container |
| `returning` | Require a completed healthy profile and test a direct launch |

`first-run`, `resume`, `update`, and `doctor` ask for confirmation. Each profile
gets its own container, machine, volumes, and application-data directory.
`--yes` is available for disposable automated test machines. These scripts
never uninstall Podman, disable WSL, or touch the standalone CLI environment
because those components may be shared with other applications.
Use a disposable VM when testing installation of system-level prerequisites
from an entirely clean computer.

Examples:

```bash
./linux.sh --scenario first-run
./macos.sh --release choose --scenario update
```

```powershell
.\windows.ps1 -Scenario FirstRun
.\windows.ps1 -Release v0.1.0-alpha.4 -Scenario Update
```

Profiles are named and reusable. Pass `--profile upgrade-a` on Linux/macOS or
`-Profile upgrade-a` on Windows to keep multiple scenarios side by side.
The Windows helper installs or replaces the normal per-user application binary,
but launches it with the selected isolated test profile.
