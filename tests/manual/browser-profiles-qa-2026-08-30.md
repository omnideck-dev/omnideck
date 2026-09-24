# Browser profiles QA result — 2026-08-30

## Run

```text
Target: http://127.0.0.1:8080
Worktree: browser-profile-ux
Started: 2026-08-30 10:44 CDT
Completed: 2026-08-30 10:49 CDT
Driver: Playwright Chromium, 1440 × 1000
Result: pass; one product defect found and subsequently fixed
```

The run attached to the user's initialized development instance. It used a
local fixture with disposable Browser profiles and agents. Default and every
preexisting profile were treated as read-only.

## Passed

- Browser navigation, toolbar controls, and user-facing terminology.
- Save disclosure and informational site inventory.
- Creating named profiles with product/custom icons from Empty.
- Empty Browser behavior.
- Cookie, local-storage, and IndexedDB isolation between two saved profiles.
- Unsaved working-Browser changes disappearing after the profile is reloaded.
- Explicitly overwriting an existing profile.
- Saving as a new profile from an existing profile.
- Saving without changing the current page or tabs.
- Settings identity editing, icon editing, base-domain grouping, search/paging,
  and Default's delete protection.
- Open in Browser confirmation and cancellation on the initial request.
- Individual-domain removal with a confirmation dialog.
- Clearing all state while retaining the profile identity.
- Agent Browser-access configuration and Starting-profile persistence.
- Browser being absent from the ordinary skill picker.
- Full-width Starting-profile menu and readable option labels.
- Singular and plural assigned-agent deletion guards.
- Compact assigned-agent footer without nested gray reference rows.
- Removing assignments and deleting disposable profiles.
- Light- and dark-theme visual review.
- Cleanup and restoration of the user Browser to Default.

## Defect found and fixed

### Cancelled Open in Browser request returns after remount

Reproduction:

1. Open **Settings → Browser** and select a saved profile.
2. Click **Open in Browser**.
3. Click **Cancel** in the load confirmation.
4. Refresh the application or otherwise remount the Browser view.

Observed:

- The same load confirmation returns.
- Its modal scrim intercepts navigation until it is cancelled again.

Expected:

- Cancelling consumes the navigation request permanently.
- Remounting Browser does not recreate a cancelled confirmation.

The initial cancellation does not load or modify Browser state. This is a
navigation-state defect rather than a profile-isolation failure.

Resolution verified on 2026-08-30:

- Cancelling or completing the load now consumes the stored navigation request.
- A focused component regression covers cancellation followed by a Browser remount.
- The rebuilt Playwright E2E reproduced the original flow and confirmed that the
  modal remains dismissed after a full page reload.

## Blocked on this live instance

- Real-account sign-in validation: no disposable QA credentials were supplied.
- Root-agent Browser and takeover execution: the running instance uses real
  providers rather than the deterministic mock provider.
- Full process-restart persistence: this would stop the user's running
  development application.

These behaviors retain automated integration/E2E coverage, but this run does
not claim a manual pass for them.

## Test-maintenance follow-up

The checked-in E2E case for removing a profile domain was updated to use the
current confirmation dialog. The Browser-profile E2E suite now also verifies
that selecting the already-loaded profile is a no-op.

## Cleanup verification

```text
Temporary Browser profiles remaining: 0
Temporary agents remaining: 0
Browser restored to: Default
Default raw site records before/after: 290 / 290
Other preexisting profile raw site records before/after: 16 / 16
```
