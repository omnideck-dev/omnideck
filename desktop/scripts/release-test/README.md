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

`CHECKLIST.md` is the per-release manual pass: what to run, in what order, and
what each screen should say. It covers only what automated tests cannot — the
elevation prompts, the operating system's own install warnings, and how it looks
on a real display.

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
`--yes` is available for disposable automated test machines.

The scenarios above reset the *application*, never the host. To test the
prerequisite installation itself, use the dependency reset below.

## Testing from a completely clean computer

`reset-host.sh` and `reset-host.ps1` return the machine to a pre-install state:
podman is uninstalled and the isolated test machine is destroyed, so the next
launch installs its prerequisites from scratch.

```bash
./reset-host.sh --inventory     # list what would be removed and what is kept
./reset-host.sh --dry-run       # show every step without running it
./reset-host.sh                 # uninstall podman after confirmation
```

```powershell
.\reset-host.ps1 -Inventory
.\reset-host.ps1 -DryRun
.\reset-host.ps1                # uninstall podman
.\reset-host.ps1 -IncludeWsl    # also uninstall WSL (distributions are kept)
```

### What is never touched

The reset only removes resources whose names it derives from the test
namespace. Everything else is preserved:

- **Containers and volumes are never deleted** unless they are the namespaced
  test container or its two test volumes. The standalone CLI's `omnideck`
  container and `omnideck-home` / `omnideck-state` volumes are not test
  resources and are left alone.
- **Container storage stays on disk.** Uninstalling the podman package does not
  remove `~/.local/share/containers`, so every image, container, and volume
  reappears when podman is reinstalled.
- **Only the namespaced podman machine is destroyed.** Other machines — including
  the application's normal `omnideck-runtime` — are preserved. This matters most
  on macOS and Windows, where a machine holds all the containers inside it.
- **WSL distributions are never unregistered.** `-IncludeWsl` removes the WSL
  feature with `wsl --uninstall`, which leaves every distribution's disk intact.
- `purge` and `autoremove` are never used on Linux, so podman's removal cannot
  cascade into unrelated packages.

Run `--inventory` first. It prints every container, volume, and machine on the
host, marking each `REMOVE` or `preserved`. If a name you care about shows as
preserved, the reset will not touch it.

A full first-install pass is therefore:

```bash
./reset-host.sh --inventory     # confirm nothing of yours is in scope
./reset-host.sh                 # uninstall podman
./linux.sh --scenario first-run # install and set up from nothing
```

A disposable VM is still the strictest test, because a reset cannot undo
system changes made by an earlier install that the uninstaller leaves behind.

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
