# Browser profiles manual QA script

## Purpose

Verify that a user can explicitly save Browser sign-ins as named profiles,
load and manage those profiles, and give different root agents isolated Browser
starting states without accidental persistence or cross-profile leakage.

This procedure intentionally uses the real product UI. Do not use API calls or
developer tools to set up state that a user is expected to create themselves.

## Safety and prerequisites

- Run this against a disposable OmniDeck data directory or a development
  installation whose Browser profiles and agents may be changed.
- Use disposable QA accounts. Do not save personal, production, financial, or
  administrator sessions into a Browser profile used for this test.
- Prefer two QA accounts on the same service. Seeing account A and account B on
  the same account page makes isolation unambiguous.
- Have a second, independent test site available for the explicit-save test.
  Avoid a site that silently signs in through the first site's identity provider.
- Keep the same OmniDeck data directory when performing the restart test.
- A site's own session can expire or be revoked. If a saved login unexpectedly
  fails, confirm the account can still sign in before treating it as an OmniDeck
  failure.

Record the test inputs before starting:

```text
Date/time:
Tester:
Branch/commit:
OmniDeck launch mode/build:
Operating system:
Theme:

Primary service account page:
QA account A:
QA account B:
Secondary test site/account:

Profile A name: QA Account A
Profile B name: QA Account B
Copy profile name: QA Account A Copy
Agent A name: QA Browser Agent A
Agent B name: QA Browser Agent B
Empty agent name: QA Empty Browser Agent
```

For every numbered section, record `PASS`, `FAIL`, or `BLOCKED` and attach a
screenshot for any failure or visual defect.

## Release-blocking failures

Stop and report the issue immediately if any of these occur:

- One profile or agent can see a different profile's signed-in account.
- Browsing changes a saved profile without an explicit save.
- Saving or loading one profile changes another saved profile.
- An agent writes its Browser changes back to a profile without an explicit
  takeover save.
- Empty starts with saved sign-ins.
- A profile can be deleted while an enabled agent uses it.
- Loading, removing a site, or clearing state affects the wrong profile.
- The user-facing UI refers to a "root Browser."

## 1. Navigation and initial state

1. Open OmniDeck and select **Browser** from the left navigation.
2. Verify Browser is a single destination with no Browser submenu.
3. Verify the Browser address row contains:
   - A Browser-state control showing the current profile or **Empty**.
   - A camera icon whose accessible label or tooltip is **Save Browser state**.
4. Open the profile selector.
5. Verify **Default** and **Empty** are available. Existing saved profiles may
   also appear, along with **Manage browser profiles**.
6. Select the profile already shown in the control and verify the selector
   closes without showing a load confirmation or changing the Browser.
7. Verify the screen never uses the term "root Browser."

Expected:

- Browser feels like a regular user-controlled Browser.
- Profile management is reached through Settings, not a left-navigation submenu.
- The initial Browser for a newly started OmniDeck process is loaded from
  **Default**, even if another profile was used before the previous shutdown.

Result: `__________`

## 2. Create profile A from Empty

1. Choose **Empty** from the Browser-state control.
2. In the confirmation dialog, verify it warns that current tabs and changes
   not saved to a profile will be discarded.
3. Confirm **Use Empty**.
4. Verify the old tabs close and the new Browser does not contain a previous
   signed-in session.
5. Navigate to the primary service and sign in as QA account A.
6. Open an account page that visibly identifies account A.
7. Click the camera icon.
8. In **Save current Browser as a profile**, verify:
   - The warning explains that agents using this profile can access sites where
     this Browser is logged in.
   - **Save as** defaults to **Create new profile**.
   - The sites being saved are listed for information only; there are no
     per-site inclusion controls.
   - Related subdomains are presented as recognizable base sites where possible.
   - The profile name is required.
9. Enter **QA Account A** and choose a recognizable product or custom icon.
10. Save the new profile.
11. Verify the Browser remains on the same page, account A remains signed in,
    and open tabs are not disturbed by saving.
12. Verify the Browser-state control now shows **QA Account A**.

Expected:

- Saving is explicit and does not reload or otherwise modify the working Browser.
- The new profile is associated with the Browser state that produced it.

Result: `__________`

## 3. Create profile B and prove account isolation

1. Choose **Empty** again and confirm the replacement.
2. Visit the primary service account page.
3. Verify account A is not already signed in.
4. Sign in as QA account B.
5. Save the Browser as a new profile named **QA Account B** with a different icon.
6. Load **QA Account A** through the Browser-state control and confirm the replacement.
7. Visit the primary service account page and verify it shows account A.
8. Load **QA Account B**, visit the same page, and verify it shows account B.
9. Load **Empty** and verify neither account is signed in.

Expected:

- Each saved profile restores only its own account state.
- Loading Empty provides no saved profile state.
- Loading a profile restores site state, not the profile's previous tabs or
  browsing history.

Result: `__________`

## 4. Verify that browsing never auto-saves

1. Load **QA Account A**.
2. Confirm account A is still signed in on the primary service.
3. Visit the secondary test site and sign in or create an obvious persisted
   preference. Do not click **Save Browser state**.
4. Load **Empty**, then load **QA Account A** again.
5. Confirm account A is still available.
6. Visit the secondary test site.

Expected:

- The secondary site's unsaved state is absent.
- Merely browsing while a profile is loaded did not update the saved profile.

Result: `__________`

## 5. Explicitly update an existing profile

1. While **QA Account A** is loaded, recreate the secondary site's test state.
2. Click **Save Browser state**.
3. Verify **Save as** defaults to **Update QA Account A**.
4. Verify **Create new profile** is also available.
5. Choose **Update QA Account A** and save.
6. Verify the current page and tabs remain unchanged after saving.
7. Load **Empty**, then reload **QA Account A**.
8. Verify both account A and the secondary site's state are restored.
9. Load **QA Account B** and verify the secondary state was not added to B.

Expected:

- Overwriting an existing profile requires an explicit save.
- Only the selected destination profile changes.

Result: `__________`

## 6. Create a profile from a previously saved profile

1. Load **QA Account A**.
2. Click **Save Browser state** and choose **Create new profile**.
3. Name it **QA Account A Copy** and choose another icon.
4. Save it.
5. Load **QA Account A**, **QA Account A Copy**, and **QA Account B** in turn.

Expected:

- The copy initially has the same saved sign-ins as A.
- B remains isolated.
- Creating the copy does not modify A.

Result: `__________`

## 7. Manage profiles in Settings

1. From Browser, click the gear icon.
2. Verify OmniDeck opens **Settings → Browser**.
3. Verify the profile list includes Default, A, B, and A Copy with their chosen
   icons and site counts.
4. Select **QA Account A Copy**.
5. Verify the identity icon, name field, and saved date align cleanly.
6. Rename it to **QA Account A Managed** and choose another icon, then save.
7. Switch to another profile and back. Verify the new name and icon persist.
8. If the profile contains related subdomains, verify Settings groups them under
   the recognizable base domain rather than showing one row per subdomain.
9. If a profile has more than six grouped sites, verify:
   - The site list is paginated.
   - Previous and next controls work.
   - Searching finds a site regardless of its current page.
10. Click **Open in Browser**.
11. Verify OmniDeck returns to Browser and asks before replacing its state with
    **QA Account A Managed**.
12. Cancel once and verify the current Browser is unchanged. Repeat and confirm
    the load.

Expected:

- Profile management remains in Settings.
- Names, icons, grouping, search, paging, and Open in Browser match the rest of
  the product's design language.

Result: `__________`

## 8. Remove one site's saved state

Use **QA Account A Managed** for this destructive test.

1. In **Settings → Browser**, select **QA Account A Managed**.
2. Find the secondary site in **Sites in this profile**.
3. Verify its muted trash icon is visible without requiring hover and becomes
   more prominent on hover or focus.
4. Click the trash icon.
5. Verify a confirmation dialog identifies the site and profile.
6. Cancel and confirm nothing changes.
7. Repeat, then confirm **Remove site**.
8. Verify the site disappears and the profile's site count updates.
9. Open this profile in Browser.
10. Verify account A remains signed in but the secondary site's saved state is
    absent.

Expected:

- Removing a grouped site removes its represented domain state only from this
  profile.
- Other profiles and other sites in the same profile remain intact.

Result: `__________`

## 9. Clear all state without deleting the profile

Continue using **QA Account A Managed**.

1. In Settings, click **Clear profile state** once.
2. Verify the control changes to **Clear all state?** and no state is removed yet.
3. Click it again to confirm.
4. Verify the profile still exists with the same name and icon but shows zero
   saved sites.
5. Verify the clear control is disabled while the profile is empty.
6. Open it in Browser and verify it contains no saved sign-ins.

Expected:

- Clearing state resets the profile to Empty without deleting its identity.

Result: `__________`

## 10. Configure agents

1. Open **Agents** and create **QA Browser Agent A**.
2. In its Browser section, verify:
   - **Allow Browser access** is a single capability toggle.
   - Browser is not shown as an addable skill.
   - The profile field is labelled **Starting profile**.
3. Enable Browser access.
4. Verify the Starting profile selector includes **Empty** and all saved profiles.
5. Select **QA Account A** and save the agent.
6. Reopen the agent and verify the setting persisted.
7. Create **QA Browser Agent B**, enable Browser access, and select
   **QA Account B**.
8. Create **QA Empty Browser Agent**, enable Browser access, and select **Empty**.
9. Verify profile icons and long names render without a clipped or broken menu.

Expected:

- Browser configuration is one coherent section, not a skill plus separate
  settings.
- Empty means the agent starts without a saved profile.

Result: `__________`

## 11. Verify root-agent isolation

Use this prompt with the appropriate account page substituted:

```text
Open <PRIMARY ACCOUNT PAGE> and tell me which QA account is signed in. Do not
enter credentials, sign out, or change the account.
```

1. Start a new conversation with **QA Browser Agent A** and send the prompt.
2. Open its Browser preview or take control and verify account A is visible.
3. In the same conversation, select **QA Browser Agent B** for the next turn and
   send the same prompt.
4. Verify the old Browser tabs close/reopen as the context changes and account B
   is visible. Account A must not remain active.
5. Start a new conversation with **QA Empty Browser Agent** and send the prompt.
6. Verify the service presents a signed-out page.
7. In the Empty conversation, take control and sign in as account A, but do not
   save Browser state.
8. Continue the same conversation for one turn and verify the live session is
   still available.
9. Start a different conversation with **QA Empty Browser Agent** and revisit the
   account page.

Expected:

- Root-agent Browser state survives turns within the same conversation.
- Switching root agents replaces the cached Browser with the selected agent's
  Starting profile.
- A new Empty conversation does not inherit the prior conversation's state.

Result: `__________`

## 12. Save during takeover

### Existing profile

1. Return to a conversation using **QA Browser Agent A**.
2. Let the agent open a site, then take control of the Browser.
3. Create a harmless new saved state on the secondary test site.
4. Click the takeover camera icon.
5. Verify **Save as** offers:
   - **Update QA Account A**.
   - **Create new profile**.
6. Verify it does not offer an unrelated profile as an overwrite destination.
7. Update **QA Account A**.
8. Verify the live Browser remains on the same page and usable after saving.
9. Start a new conversation with Agent A and verify the saved update is present.

### Empty

1. Start a new conversation with **QA Empty Browser Agent**.
2. Let it open the primary service, take control, and sign in with a disposable
   QA account.
3. Click the takeover camera icon.
4. Verify only **Create new profile** is available and a name is required.
5. Enter **QA Takeover Profile**.
6. Verify **Use this profile for QA Empty Browser Agent next time** is present and
   unchecked by default.
7. Check it and save.
8. Verify the current Browser stays open and signed in.
9. Reopen the agent configuration and verify its Starting profile is now
   **QA Takeover Profile**.
10. Start a new conversation with that agent and verify the login is available.

Expected:

- Takeover saves only when the user explicitly requests it.
- Saving from Empty can optionally assign the new profile, with confirmation.
- Agent browsing never writes back automatically.

Result: `__________`

## 13. Assigned-profile deletion safeguard

1. In **Settings → Browser**, select **QA Account B** while Agent B still uses it.
2. Click **Delete**, then click **Delete profile?** to confirm.
3. Verify deletion is blocked by a compact danger callout.
4. Verify the callout:
   - Says the profile is in use.
   - Reports the correct number of agents.
   - Names **QA Browser Agent B** in the separated footer.
   - Does not use a nested gray reference card.
5. Verify **QA Account B** still exists and remains usable.
6. Assign a second enabled QA agent to B and retry deletion.
7. Verify both agent names and the plural agent count are shown.
8. Change every listed agent's Starting profile to **Empty** or another profile.
9. Retry the two-click deletion and verify it succeeds.
10. Select **Default** and verify no delete action is available.

Expected:

- The UI identifies exactly which enabled agents prevent deletion.
- A profile becomes deletable after those assignments are removed.

Result: `__________`

## 14. Restart persistence

Perform this section before deleting the remaining QA profiles.

1. Note the saved sites and assigned agents for the remaining QA profiles.
2. In the working Browser, create one additional unsaved site state.
3. Fully stop and restart the OmniDeck backend/application using the same data
   directory. A page refresh alone is not sufficient.
4. Open Browser.
5. Verify it starts from **Default**, not the last custom profile or Empty.
6. Load **QA Account A** and verify its explicitly saved state survived.
7. Verify the unsaved state from step 2 did not become part of A.
8. Reopen Agents and verify their Browser access and Starting profile settings
   survived.
9. Start a new agent conversation and verify the assigned profile still restores.

Expected:

- Saved profiles and agent assignments survive a process restart.
- The temporary user Browser session and unsaved changes do not.
- Default is the initial source for the new user Browser process.

Result: `__________`

## 15. Visual and interaction review

Repeat the principal screens in both light and dark themes if both are in scope.

- [ ] No unexplained green status dots appear.
- [ ] Product icons render correctly in lists, pickers, and agent selectors.
- [ ] Profile identity icon, label, input, and saved date align correctly.
- [ ] Profile and site lists scroll or paginate without clipping the detail pane.
- [ ] Select menus are wide enough to read profile names and show selection.
- [ ] Icon-only Browser controls have useful hover text and keyboard focus.
- [ ] Destructive controls are visible but appropriately subdued until hover.
- [ ] Confirmation dialogs name the affected profile or site.
- [ ] Browser profile management looks native to Settings and the SIGNAL design
      language.
- [ ] No UI claims it knows which account a site's saved data represents.
- [ ] No UI exposes implementation terms such as root Browser, storage state, or
      browser pool.

Result: `__________`

## Cleanup

1. Change all QA agents to **Empty** or disable their Browser access.
2. Delete the QA agents.
3. Delete all non-Default profiles created by this procedure:
   - QA Account A
   - QA Account A Managed, if it still exists
   - QA Takeover Profile
   - Any additional copy or shared-assignment profile
4. If Default was renamed or edited during exploratory testing, restore its
   original name and intended saved state.
5. Delete profile state does not revoke the site's server-side session. Log out
   or revoke disposable QA sessions separately if required by your test policy.
6. Record any residual profiles, agents, processes, files, screenshots, and issue
   links.

## Final result

```text
Core result: pass | fail | blocked
Start/end timestamps:
Failed section(s):
Issue links:
Screenshot/video/log locations:
Cleanup complete: yes | no
Notes:
```
