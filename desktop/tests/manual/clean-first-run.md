# Clean-machine first-run test

## Automation boundary

The Linux and Windows VM journeys automate clean install, setup copy/DOM,
permission cancellation/approval, hosted open, recovery, and package lifecycle.
The clean Windows lane also drives SmartScreen, restart-now, and RunOnce
reopening. Run this procedure manually for native macOS or another target without
an available automation host; otherwise use it only for subjective visual or
accessibility review listed in `manual-remainder.json`.

## Starting state and safety

- Use a disposable VM snapshot or a dedicated, restorable machine.
- Capture installed applications, WSL/Podman state, running processes,
  containers, machines, volumes, ports, and existing OmniDeck state.
- On Linux or macOS, run `reset-host.sh --inventory` and confirm every item
  marked `REMOVE` belongs to the test namespace.
- On Windows, run `reset-host.ps1 -Inventory`. The destructive reset removes
  every WSL distribution and all Podman and OmniDeck state. Continue only on a
  confirmed disposable Windows test host, then reset, restart, and inventory
  again.

## Procedure

1. Complete the [published artifact](published-artifact.md) checks.
2. Install and launch through the normal user-facing path. Confirm a desktop
   window appears promptly and no terminal window accompanies it.
3. Capture each setup screen. Compare DOM structure, visible text, phases,
   progress copy, and recovery copy with the frozen parity reference under
   `desktop/tests/fixtures/electron-setup`.
4. Confirm the sequence and visible copy:
   - `Starting omnideck` appears immediately while checks run.
   - `Welcome to omnideck` offers only `Set up omnideck` and shows the Agent
     Dash note.
   - `Getting your computer ready…` appears above a progress bar without a
     component list.
   - `Waiting for your permission` appears before the OS prompt and explains
     what is being installed without claiming access to the user's password.
   - `Preparing a secure space to run in…` appears only where required.
   - `Downloading omnideck’s files…` reports meaningful progress.
   - `omnideck is ready` offers `Open omnideck`.
5. Confirm light/dark selection follows the OS and Agent Dash remains smooth
   during setup.
6. At the elevation or permission prompt, dismiss once. Confirm the application
   classifies the cancellation as a permission failure and offers `Try again`.
7. Retry and approve. Confirm secure-space preparation appears on Windows and
   macOS but not Linux.
8. If Windows requests a restart, confirm progress is saved, restart, sign in,
   and verify setup resumes without duplicating resources.
9. During image download, confirm phase copy and progress move plausibly.
10. Continue to `omnideck is ready`, open the hosted application, and verify it
   returns HTTP success on its dynamically assigned loopback origin.
11. Record the bundled CLI version/commit, runtime schema, container image
    digest, final process list, and final resource inventory.

## Pass criteria

The published package completes the real first-run journey, expected permission
and restart paths work, the hosted application opens, pinned supply-chain data
matches, and no unrelated resources change.
