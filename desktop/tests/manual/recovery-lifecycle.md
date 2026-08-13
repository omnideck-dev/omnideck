# Recovery and package lifecycle test

## Automation boundary

The disposable Linux and Windows VM suite owns deterministic returning, Doctor,
resume, update, occupied-port recovery, interrupted-window recovery, install,
reinstall, uninstall, and reinstall-after-uninstall assertions. Do not repeat
those as manual release gates after their automated lane passes. This procedure
retains only live network interruption, sleep/wake, destructive interruption
timing, native platforms without an automation lane, and investigation of an
automated failure.

## Scenario helpers

When investigating an automated failure or covering an unavailable native
platform, use the published-release helpers for `returning`, `doctor`, `resume`,
and `update`. Linux and macOS use isolated named profiles. Windows deliberately
uses the product's normal WSL-backed runtime path.

For each scenario, record the starting state, helper command, visible phases,
diagnostics, result, process list, and resource inventory.

- `returning` briefly shows `Starting omnideck`, then opens the hosted app
  without Welcome, setup progress, or Agent Dash instructions.
- `doctor` identifies the failed phase, preserves completed/pending phase
  classification, and makes the inline `Technical details` disclosure usable.
- `resume` shows `CONTINUING SETUP`, states that completed work was retained,
  and continues without another start button.
- `update` shows `Bringing omnideck up to date` and does not request unrelated
  elevation.

## Controlled interruptions

1. Disconnect the network during download, restore it, and verify bounded,
   actionable recovery.
2. Suspend and resume the host while setup or the hosted application is active;
   verify recovery and process ownership remain coherent.
3. Interrupt power or the process at a deliberately selected destructive timing
   boundary, then restore the disposable host and verify recovery.
4. Stop the runtime or application container while OmniDeck is open only when
   investigating the corresponding automated assertion. Verify
   diagnostics and recovery do not expose raw internals as the only guidance.

Occupied saved-port recovery is no longer manual. Every Linux and Windows VM
lane creates the conflict, locks the visible wording, and proves automatic
selection and persistence of another port; see `tests/e2e/README.md`.

## Package lifecycle

Linux and Windows package lifecycle is automated. Perform clean install,
reinstall, uninstall, and reinstall-after-uninstall manually only on native
targets without an available automation lane. Verify launchers, shortcuts,
receipts, mounted images, executables, and host processes. Confirm ordinary app
uninstall does not remove unrelated Podman resources or user container data.

The destructive release-test reset is a lab tool, not product uninstallation;
never use it as evidence that the uninstaller behaved correctly.
