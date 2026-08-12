# Recovery and package lifecycle test

## Scenario helpers

After a successful first run, use the published-release helpers for `returning`,
`doctor`, `resume`, and `update`. Linux and macOS use isolated named profiles.
Windows deliberately uses the product's normal WSL-backed runtime path.

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

1. Close the setup window during download, relaunch, and verify completed work
   is retained.
2. Disconnect the network during download, restore it, and verify bounded,
   actionable recovery.
3. Stop the runtime or application container while OmniDeck is open. Verify
   diagnostics and recovery do not expose raw internals as the only guidance.
4. Reboot after partial setup and verify a single resume path.
5. Relaunch after a failed action and verify recovery remains possible.

Occupied saved-port recovery is no longer manual. Every Linux and Windows VM
lane creates the conflict, locks the visible wording, and proves automatic
selection and persistence of another port; see `tests/e2e/README.md`.

## Package lifecycle

For each shipped package format on its representative OS, perform clean install,
reinstall, uninstall, and reinstall-after-uninstall. Verify launchers, shortcuts,
receipts, mounted images, executables, and host processes. Confirm ordinary app
uninstall does not remove unrelated Podman resources or user container data.

The destructive release-test reset is a lab tool, not product uninstallation;
never use it as evidence that the uninstaller behaved correctly.
