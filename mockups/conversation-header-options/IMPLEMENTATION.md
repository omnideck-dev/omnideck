# Details menu implementation

The production ChatPanel now renders ConversationHeader, containing the title
and ConversationDetails disclosure. ConversationDesktopView assembles its data
through useConversationDetails and supplies the existing navigation callbacks.

## State and behavior

- Browser and Terminal availability is derived from existing Workspace state:
  browser tabs and terminal command records. No availability flags or backend
  resource catalog were added.
- Desktop's open-view catalog supplies “Open in workspace” versus “View closed.”
  The same row action focuses an existing view or reopens a closed one through
  the existing Workspace Desktop adapter, retaining its deterministic identity.
- The current root workspace appears once across turns. Browser and Terminal
  groups list resources by owning agent; a lone primary resource stays a single row.
- Artifacts are deduplicated across root and sub-agent output. Agents counts
  include spawned agents only; status copy describes working/finished/failed/stopped.
- Details acknowledges stable item IDs in browser local storage, scoped by
  conversation. New items while the disclosure is open are acknowledged too.
  “New” row markers remain for that opening, then clear. Repeated browser
  screenshots and additional terminal output do not create new badges.
- Escape closes the disclosure and returns focus to Details. Outside clicks
  and focus leaving the disclosure close it. The content scrolls within the
  available viewport. The shared Popover primitive anchors to the trigger,
  avoids pane clipping, and supplies placement and dismissal behavior. Chrome
  matches SIGNAL dropdown tokens, without a pointer arrow.

## Advanced

Advanced is collapsed by default and contains turns, spawned-agent count,
reported token totals, primary context proximity to compaction, and usage by agent.
Primary-agent totals aggregate all root spans across conversation turns.
Sub-agent capacity is not displayed.

Iteration events now optionally persist provider-reported total_tokens. Usage
records are keyed by iteration so duplicate delivery does not double-count.
Anthropic's separate cache counts are included; OpenAI's inclusive prompt count
is not counted twice. Old, interrupted, or unreported calls remain unknown and
produce “—” instead of an incomplete total. Counts cover reported agent-loop
model calls; this is not a billing ledger of retries or auxiliary model calls.

Cost columns are present with “—”: the current application has no pricing data.
No prices or illustrative costs are shipped as real data. The explanatory
paragraph was removed from the UI at the user's request.

## Validation

- Full frontend suite: 736 tests passed.
- Focused backend turn execution, event-model and event-log tests passed.
- Frontend lint, TypeScript, production build, Python lint/type checks, and
  generated event-contract verification passed.
- verify-implementation.py exercised the real React header components in
  Chromium with sample conversation data, including close/reopen presentation,
  acknowledgement, Escape, and dark/light layouts at 1000px and 360px widths.
- Existing container E2E navigation helpers/assertions were updated for Details;
  the full container E2E suite was not run.

Screenshots: implementation-1000-dark.png, implementation-360-dark.png, and
implementation-360-light.png in screenshots/.
