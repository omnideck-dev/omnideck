# Desktop App

Ship Omnideck as one double-clickable application. No container engine to install, no CLI to install, no terminal interaction. The user downloads an app, opens it, and Omnideck is running.

The container does not change. Every capability not behind a feature flag keeps working bit-for-bit, because the runtime it runs in is untouched — this is a packaging project, not a re-architecture.

## Current state (before this work)

Getting to a working Omnideck takes three installs and a terminal session:

1. Install Podman or Docker.
2. Install the `omnideck` CLI (Homebrew or a release binary).
3. Run `omnideck install`, answer the wizard, then open a browser.

The container itself is already the whole product. `container/Dockerfile` carries the app server, the agent runtime, the tools, Chrome, and the optional desktop; `main.py` serves the React UI and the JSON API on `PORT` (8080 by default). The host contributes a container engine and, optionally, Ollama.

Production publishes ports explicitly. `--network=host` appears only in dev and test paths (`Justfile` `dev`, `manual-test`, `e2e`), so the container is already reachable through normal port forwarding — including through `podman machine`'s gvproxy on macOS. (`plans/go_cli_wrapper.md` lists `--network=host` under "Always"; that line is stale and should be corrected when this work lands.)

## Design

### The container is frozen

The flagged capabilities — `image_generation`, `music_generation`, `visual_grounding`, `desktop`, `custom_tools` — are allowed to vary by platform. The GPU-backed three are CUDA and stay Linux-plus-NVIDIA; a Mac has no path to them and never will, and the flags already express that. Everything else — chat, profiles, multi-provider models, skills, sub-agents, multi-instance, browser automation, code execution, routines, memory, integrations, artifacts — is container-internal and must behave identically before and after.

That constraint is what makes this cheap. Replacing the container with a hand-built VM would put all of those features back on the test bench for no user-visible gain.

### Topology

```
Omnideck.app                        ← the only thing the user installs
  ├─ window → http://127.0.0.1:PORT ← the existing React UI, unchanged
  ├─ vendored: podman, gvproxy, vfkit/krunkit
  └─ vendored: omnideck engine (the CLI, headless)
        └─ private podman machine (a VM)
              └─ omnideck container (unchanged)
```

On macOS the engine's machine is already a hardware-isolated VM — `podman machine` runs libkrun/vfkit under the hood. Mac users who install Podman today already get VM-grade isolation; this work does not change the security boundary, only who installs it.

### Private engine state

The bundled engine must not touch a user's own Podman setup. Point `CONTAINERS_*` at a config directory under Omnideck's own state and provision a dedicated machine under a dedicated connection name. A developer with their own machines, images, and connections sees no interference, and uninstalling Omnideck removes only what Omnideck created.

### First run

This is the main UX surface and the bulk of the work. Machine provisioning plus a 1–2 GB image pull takes minutes before anything is usable, so it needs staged progress rather than a spinner:

1. Verify virtualization is available.
2. Initialize the private machine.
3. Pull the image (byte progress).
4. Start the container.
5. Poll `/api/settings` until it answers.
6. Open the window.

Every later launch is steps 4–6.

### Lifecycle

Opening the app starts the machine if stopped, then the container. Quitting stops the container. Whether the machine also stops on quit is a memory-versus-latency trade — stopping it returns a multi-gigabyte allocation to a laptop, at the cost of a slower next launch. Default to stopping it, and revisit if launch latency becomes the complaint.

### Host Ollama detection

On a Mac, Ollama runs natively with Metal acceleration and cannot run usefully inside the Linux guest. For the largest audience, "local models" therefore always means *host Ollama reached across the VM boundary*, which makes this the primary path rather than an edge case.

The guest cannot detect this; the shell can. The engine runs on the host, probes `127.0.0.1:11434`, and hands the wizard a pre-filled `http://host.containers.internal:11434`. This converts the most awkward onboarding step into a filled-in default, and only the host-side wrapper is in a position to do it.

### Ports

Publish to `127.0.0.1` explicitly rather than all interfaces. Today the container's `main.py` binds every interface, so a published port is reachable from the LAN with no authentication — publishing to loopback closes that, and binding loopback inside the container as well makes it defense in depth.

The shell picks a free port and passes it through the existing `PORT` environment variable, which is already exercised by `just e2e`. When the desktop flag is on, 6080 needs publishing too; `DesktopPreview.jsx` derives the noVNC URL from `window.location.hostname`, so it works as long as the port is published.

### Shell framework

Electron. The UI is already a Chromium application — the Playwright suite drives Chromium and the frontend is developed against Chrome — so bundling Chromium means users get the exact engine the tests pass in. The native side is Node, which the team already has, and child-process supervision, auto-update, and tray support are all well-paved. The ~150 MB bundle cost is noise beside a 1–2 GB guest image.

Tauri was considered and rejected: it would put the Linux build on WebKitGTK, which no part of this UI has been tested against, and add Rust as a fourth language for the sake of a bundle saving that does not matter here.

**Reduced-scope alternative:** a menu-bar app that opens the user's default browser. Identical engine work, no window framework, no rendering risk, roughly half the Phase 2 effort. The user gets a browser tab instead of an app window. Electron is a drop-in upgrade later.

## Work breakdown

### Phase 0 — this repo (small)

- Bind `127.0.0.1` in `main.py`. Defense in depth once the publish flag is loopback-only.
- Add arm64 to the e2e job. `publish.yml` builds `linux/arm64` natively on `ubuntu-24.04-arm` but the e2e job runs on `ubuntu-latest` and pulls the amd64 manifest, so the image every Apple Silicon Mac runs is published untested. Arm64 Linux runners are already in use elsewhere in the same workflow.

### Phase 1 — `omnideck-dev/cli` (small)

- Headless mode: no prompts, no TTY assumptions, machine-readable progress on stdout for the shell to render.
- Provision and manage a private machine (see *Private engine state*), rather than assuming the user brought a working engine.
- Probe the host for Ollama and pass the translated URL through.
- Publish to `127.0.0.1` rather than all interfaces.

### Phase 2 — new app bundle (the real work)

- Electron shell vendoring `podman`, `gvproxy`, `vfkit`/`krunkit`, and the Phase 1 engine binary.
- First-run progress UI.
- Signing and notarization: hardened runtime on every vendored binary, `com.apple.security.virtualization` on whichever helper actually creates the VM (not the app's main executable), notarization for the bundle.

## Compatibility

- **Existing installs.** Adopt the state at `~/.omnideck` and any existing named volumes in place. Provisioning fresh would silently orphan conversations, memory, and the credential vault.
- **The CLI keeps working standalone.** It moves inside the bundle; it does not disappear. Anyone scripting against it today is unaffected.
- **Linux and Windows.** Phases 0 and 1 are platform-neutral and change nothing for existing users. Phase 2 is Mac-first. Windows follows the same shape via WSL2, with one wart that cannot be engineered away: enabling the Virtual Machine Platform feature may require a reboot on first install.

## Open questions

- **Machine sizing.** RAM, CPU, and disk defaults for a 16 GB Mac running a VM plus Chrome plus Python. Related: whether idle memory is returned to the host, and whether the guest disk is TRIMmed so it shrinks after the agent's `apt` installs.
- **Ship the image or stream it.** A ~2 GB installer with a fast first run, versus a small installer with a multi-minute first run. Affects the first-run UI more than anything else.
- **Browser parity on arm64.** `launch.py:127` selects `channel="chrome"` only on x86_64, so Apple Silicon runs Playwright's bundled Chromium while everyone else runs Google Chrome. Correct — Google publishes no Chrome for linux/arm64 — but it means the largest audience would run the browser with the least coverage, on a product whose headline feature is browser automation. The arm64 e2e job in Phase 0 is the first step; whether the stealth patches in `tools/browser/core/launch.py` hold up under Chromium is worth measuring separately.
