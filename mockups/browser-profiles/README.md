# Browser profiles UX exploration

This click-through mockup explores how users prepare and save browser profiles
that give different agents access to different signed-in sites.

Open `index.html` and use the five numbered states in the prototype header:

1. **Browser** — Browser remains one flat left-navigation destination. Users can
   load a saved profile into the working session or use Empty. The loaded
   profile is never updated automatically.
2. **Save profile** — “Save Browser state” explicitly persists the working
   session by replacing an existing profile or creating a named, icon-bearing
   profile.
3. **Agent setup** — the agent editor selects a saved profile or Empty. Default
   is selected automatically when it is the only saved profile.
4. **Takeover** — while the user controls an agent Browser, the Browser toolbar
   exposes a deliberate Save session action. A session started from a profile
   can update it or create a new profile; Empty can only create a new profile.
5. **Manage profiles** — site inspection, assignments, icons, and removal live
   under a Browser Profiles settings tab.

## Proposed product model

- **Browser** is the user's working browser session. Product language never
  exposes a “root browser” concept.
- A **browser profile** is a named, saved copy of cookies, local storage, and
  IndexedDB used to start later browser sessions. The save flow presents a
  read-only summary and does not include passwords, open tabs, browsing history,
  extensions, or general Chrome settings.
- OmniDeck starts with one saved profile named **Default**. It can be renamed in
  Settings.
- Loading a profile copies its saved state into Browser. Browsing may change the
  working session, but never updates the loaded profile automatically.
- **Save Browser state** is the only way to create a profile or replace the
  state in an existing profile.
- **Empty** clears the working Browser session. Saved profiles remain
  unchanged until the user explicitly saves over one.
- An agent receives an isolated copy of the selected snapshot when it starts a
  browser session. Agent writes do not update Browser or the saved profile.
- **Empty** gives the agent browser access without loading a saved profile.
- A user takeover operates in the agent's isolated session. The user can use
  Save session to replace the assigned profile or create a new profile from the
  current session state. If the agent started with Empty, saving creates a new
  profile.

## Security copy represented in the mockup

The proposed capture can enumerate cookie domains, local-storage origins, and
IndexedDB origins. It cannot reliably determine whether those values represent
a current login or identify the signed-in account. The mockup therefore shows a
read-only inventory with realistic storage counts and never infers an account
from stored data.

An active cookie can still grant meaningful account access. The agent editor
surfaces that warning at assignment time and links back to the profile review in
Settings.

The save dialog states the consequence directly: agents assigned the profile
may be able to access and act in included sites where the user is signed in.

## Deliberate UX decisions

- The application frame follows the real expanded `Sidebar`, conversation
  panel, footer controls, and flat underline `TabStrip`. Browser is the only
  proposed new left-navigation destination.
- Normal Browser and takeover states follow the real `BrowserPreview` and
  `BrowserChrome` structure: page title, framed URL control row, and viewport.
- Browser Profiles uses the real Settings tab bar, Library Header, and
  master-detail editor patterns used by Skills and Integrations.
- The Browser sidebar item stays flat. Profile management is administrative
  configuration and belongs under Settings.
- Profiles use the same curated icon-grid pattern as conversation folders and
  the same square, accent-muted icon treatment as custom Apps.
- Status dots are reserved for real ready/running/complete/error/warning/idle
  state. A selected profile, an assignment, or a stored domain is not runtime
  status, so this mockup uses no status dots for those concepts.
- Assignment lives inside the existing agent editor because it is a property of
  the agent. The profile detail in Settings shows reverse usage for review.
- The agent mockup follows the real `AgentsView` and `ProfileBuilder` structure:
  a back row, a separate action bar, and flat full-width sections divided by
  rules. Browser is its own section between Skills and Autonomy.
- Browser is no longer represented as a skill. The Browser section contains the
  access toggle and starting-profile selector. Default is preselected when it
  is the only saved profile.
- The agent editor calls this the **starting profile**. Empty means no saved
  browser data is loaded.
- Takeover persistence is a user-invoked toolbar action, so saving state does
  not require a trip through Settings. Long-term management still does.
- Snapshot semantics avoid shared writes, concurrency locks, and accidental
  changes to the user's Browser.

## Questions to validate before implementation

1. Should a conversation be able to override its agent's browser profile, or is
   the agent default the only assignment surface needed initially?
2. Should routines always inherit their selected agent's browser profile, or
   eventually offer their own override?
3. Should profile snapshots be device-local only, or eventually sync between a
   user's OmniDeck installations? The mockup intentionally promises only local
   storage.
