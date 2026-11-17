# Integrations — Follow-Up Work

> Consolidated plan for what's deferred from `integrations-v1`. The shipped surface is documented in [`docs/integrations.md`](../docs/integrations.md); this file is for what's *next*.

The v1 PR shipped:

- Supervisor + broker UID split, AES-256-GCM vault crypto.
- Email broker (IMAP + SMTP) and CalDAV reads, both with reconnect-on-idle.
- App-password auth (iCloud + Gmail) via inline catalog entries.
- HTTP API: `GET / POST / PATCH / DELETE /api/integrations[/:id]`.
- React UI: master-detail Integrations tab with Add wizard, label edit, write_allowed toggle, delete.
- Container entrypoint with `gosu broker` + tmpfs sockets.
- E2E tests for the empty/unavailable/Add-modal flows.

What's *not* in v1 falls into three buckets, in roughly the order I'd ship them.

---

## Bucket 1 — Catalog & auth-plugin decomposition

**Why:** Adding new email/calendar providers (Fastmail, Outlook.com, custom IMAP) currently means editing `_catalog.py`. The plan was always for catalog entries to live as JSON files and auth plugins as standalone modules. Moving the existing iCloud + Gmail entries to that shape is a small mechanical refactor that unlocks one-file-PR additions afterward.

**Scope:**

- **JSON catalog loader.** Move `_ICLOUD` and `_GMAIL` from `_catalog.py` into `config/integrations_catalog/icloud.json` and `gmail.json`. `_catalog.py` becomes a loader that reads the dir, validates each file with the existing `CatalogEntry` Pydantic model, and fails loud if anything's malformed. (Plan: original `07-catalog.md`.)
- **Catalog endpoint.** `GET /api/integrations/catalog` (list) and `GET /api/integrations/catalog/:slug` (one merged entry). Today the UI hardcodes `PROVIDERS` in `AddIntegrationModal.jsx` — switch it to fetch from the endpoint.
- **`auth_plugins/` package.** Extract `app_password` (iCloud + Gmail) and `api_key` (used later by GitHub) into standalone modules with `FIELDS` + `ENV_INJECTION`. Catalog `auth_plugin` field references them by name. (Plan: `04-auth-plugins.md`.)
- **Field overrides.** Per-provider tweaks live in the catalog entry's `field_overrides` block (deep-link URL, hint text, regex). Today these are baked into the React provider list.

**Out of scope for this bucket:** new providers. The point is to make adding them cheap, not to add a bunch at once.

**Tests:**

- Pydantic round-trip on each JSON file at startup; fail-loud test that a malformed file kills the supervisor.
- Golden snapshot of the merged `/catalog/icloud` response so accidental schema drift fails CI.
- e2e: Add modal still works (provider list now comes from the API).

---

## Bucket 2 — MCP integrations

The original stdio-first design here has been superseded by
[`plans/mcp_integration.md`](mcp_integration.md). The current design starts
with remote Streamable HTTP, makes OAuth a first-class flow, uses the official
SDK for modern and legacy protocol compatibility, and defers arbitrary stdio
servers until they can run without access to the shared credential vault.

GitHub, Linear, Notion, Home Assistant, and similar services become optional
presets over the generic MCP connection model rather than separate broker
implementations. Provider selection and prioritization should happen after the
generic broker and OAuth path pass interoperability and security testing.

---

## Bucket 3 — Operational & UX polish

**Why:** Each item below is independently useful but not blocking either of the buckets above. Order is rough priority.

- **Connection pool + resolve cache** in `broker_client._call`. Today the comment at the top says "walking-skeleton shape: no resolve-cache, no connection pool, one UDS connection per call()". Under heavy agent use this hammers the supervisor's RPC. ~500ms TTL on resolve, per-broker connection pool with idle eviction.
- **`/api/integrations/events` (SSE).** State-change push to the UI so the integrations list updates live when a broker flips to `auth_failed` mid-session. Today the UI only refreshes on PATCH/DELETE round-trips.
- **REST verb split.** Today `PATCH /api/integrations/:id` covers label and write_allowed. The original plan also called for `/verify`, `/reconnect`, `/enable`, `/disable` as distinct endpoints. Add when the UI grows the affordances.
- **Calendar writes** (`create_event`, `update_event`, `delete_event` on `_caldav_client.py`). The verb names exist in `_VERB_TYPE` but the handlers aren't wired; today they error as `BAD_REQUEST: "verb not implemented"`. Either remove the type-table entries until shipped or wire the handlers + UI affordance.
- **IMAP `flag_message`.** Set/clear `\Seen`, `\Flagged`. Single message and bulk variant matching `move_messages` shape.
- **Downloads-dir GC sweeper.** Email-attachment side-channel writes to `/run/cvault/attachments/`; broker holds ownership but there's no scheduled cleanup. Add a 60s sweep that prunes anything older than N minutes.
- **Search v2.** Today `search_messages` exposes IMAP `SEARCH TEXT` only. Real Gmail uses `X-GM-RAW`; iCloud's IMAP supports more criteria. The agent-facing tool currently just passes a string; richer search would benefit from structured criteria (from/to/subject/before/after).
- **`broker_client` error class hierarchy.** Today every wire error becomes `IntegrationError`; callers that want to differentiate AUTH from NETWORK have to string-match the message. Split into subclasses for AUTH / NETWORK / UPSTREAM / BAD_REQUEST.
- **Cancellation safety in IMAP/CalDAV clients.** A verb coroutine cancelled mid-`to_thread` orphans the worker thread, which can mutate `self._imap` / `self._principal` after the next call has acquired the lock. Race, not a deadlock. Fix is structural — the worker thread should observe a cancellation signal or the lock should bracket the entire to_thread span tighter.

---

## Notes on ordering

Bucket 1 is small and removes friction for everything after it. Bucket 2 is the bigger lift but unblocks GitHub/Linear/Notion/etc. Bucket 3 items are mostly independent — pull them off the shelf as users hit the rough edge.
