# Desktop release scenario testing

These scripts download and launch a published desktop release:

- `linux.sh`
- `macos.sh`
- `windows.ps1`

They require an authenticated [GitHub CLI](https://cli.github.com/) session.
Use `--release choose` / `-Release choose` to select a recent release, or pass a
tag such as `v0.1.0-alpha.6`.

These scripts do not compile or launch the source tree. `windows.ps1` downloads
and installs a published GitHub release. `reset-host.ps1` only resets the host;
it is independent of which build created the installed state. To test a local
build after resetting and restarting, launch the target-qualified CLI beside the
release executable or the installer under
`desktop/src-tauri/target/<target>/release/bundle` directly.

Linux and macOS still support named test profiles. Windows intentionally does
not. The Windows script uses the normal application state, the normal
`omnideck-runtime` Podman machine, and the normal container and volume names.
Running a second, isolated WSL-backed Podman machine on the same Windows host
can interfere with the real runtime, so it does not represent the experience we
want to test.

`CHECKLIST.md` is the manual release pass for elevation prompts, operating
system install warnings, restarts, and real-screen behavior that CI cannot
exercise.

## Scenarios

| Scenario | What it exercises |
| --- | --- |
| `keep` | Launch without changing the current state |
| `first-run` | Remove the app container, machine, volumes, and app data |
| `resume` | Remove the app container and simulate interrupted setup |
| `update` | Remove the app container and mark the pinned environment as older |
| `doctor` | Remove the app container so diagnostics run at launch |
| `returning` | Require completed healthy setup and test a direct launch |

The mutating scenarios ask for confirmation. `--yes` or `-Yes` is available on
a disposable test computer.

## Windows: restore the whole computer to pre-WSL state

`reset-host.ps1` is deliberately destructive. This repository uses a dedicated
Windows computer as a realistic fresh-user test host, so the script does not
try to isolate or preserve any WSL, Podman, CLI, or desktop workload.

It removes:

- every registered WSL distribution and its distribution app;
- every Podman machine, container, image, and volume;
- Podman and the WSL app package;
- the WSL Windows optional features;
- the installed omnideck desktop app, desktop state, CLI state, test profiles,
  shortcuts, and pending setup-resume entry.

It keeps source repositories, downloaded installers, and local build outputs so
the CLI and desktop installer remain available after the reset.

Run from an Administrator PowerShell, or approve the single Windows elevation
prompt when the script relaunches itself:

```powershell
.\reset-host.ps1 -Inventory        # show the current state; change nothing
.\reset-host.ps1 -DryRun           # describe the destructive reset; change nothing
.\reset-host.ps1 -PreserveWsl      # remove Podman/omnideck but keep WSL installed
.\reset-host.ps1                   # reset after a typed confirmation
.\reset-host.ps1 -Yes -Restart     # reset unattended and restart Windows
```

A restart is mandatory after WSL features are disabled. After sign-in, verify
the host before starting a test:

```powershell
.\reset-host.ps1 -Inventory
```

The inventory should report no omnideck application, no Podman package, no WSL
package or distributions, both Windows features disabled, and no installed
state directories.

Test the CLI and desktop flows independently. Testing either one installs
prerequisites and changes the host, so reset and restart again before testing
the other:

```powershell
# Clean host -> CLI test
..\..\src-tauri\target\x86_64-pc-windows-msvc\release\omnideck-cli.exe

# Reset and restart again -> desktop test
.\windows.ps1 -Scenario FirstRun
```

`windows.ps1 -Scenario FirstRun` removes normal application resources; it does
not uninstall prerequisites. Use `reset-host.ps1` whenever the WSL and Podman
installation flow itself is under test.

## Linux and macOS

The shell helpers retain their named, isolated profiles because they do not use
Windows WSL distributions:

```bash
./linux.sh --scenario first-run
./macos.sh --release choose --scenario update
./reset-host.sh --inventory
```

Profiles are named and reusable with `--profile`. The isolated resource
namespace requires `v0.1.0-alpha.4` or newer.

Windows examples:

```powershell
.\windows.ps1 -Scenario FirstRun
.\windows.ps1 -Release v0.1.0-alpha.6 -Scenario Update
```
