# Iframe content in the page view (per-frame walker)

Make `browse_page()` show interactive elements from **every** frame on a page —
not just the main frame or a single dominant one — and let `click()` /
`fill_field()` / `select_option()` target them by ref. This replaces the
size-gated "dominant frame" switch with a general per-frame walk-and-merge, and
keeps working for cross-origin frames.

## Current state (before this work)

Two mechanisms surface iframe content, and both are partial:

- **Dominant-frame switch** (`Browser._detect_dominant_frame` / `active_view`).
  When one iframe covers >25% of the viewport, the tools operate *entirely
  inside* that frame — `active_view().frame` becomes the iframe's Playwright
  `Frame`, and the walker runs there. This works for same- and cross-origin
  frames (Playwright injects into every frame over CDP, so `frame.evaluate`
  reaches cross-origin content). But it handles exactly one frame, only when
  it's large, and hides the host page while active.
- **The DOM walker** (`page_view.py`) walks a single frame's `document.body`
  and never descends into child frames.

So a page with a small booking widget, or several iframes, shows none of their
controls. The GitHub issue proposed descending via `iframe.contentDocument`,
but that runs as page JS and is **same-origin only** — it would go blind on
cross-origin widgets the dominant-frame path handles today. So it's not the
right primitive.

## Design

Walk each Playwright `Frame` and merge the results into one page view, with
refs scoped to their owning frame.

1. **Per-frame walk.** For each frame in `page.frames` (already includes
   cross-origin frames), run the existing snapshot JS via `frame.evaluate`.
   Because Playwright injects per-frame, this works regardless of origin — no
   `contentDocument` access, no same-origin restriction. Run them concurrently
   (`asyncio.gather`).

2. **Splice into document order.** The main-frame walk emits an "iframe
   placeholder" node where each `<iframe>` element sits. In Python, replace each
   placeholder with that child frame's nodes (recursively for nested frames), so
   the merged output reads top-to-bottom the way the page renders.

3. **Frame-scoped refs.** Namespace refs so a ref carries which frame it lives
   in — e.g. an integer per frame plus a frame index (`data-ct-ref` stays
   frame-local; the ref string the agent sees encodes the frame). Resolution
   maps the ref back to its Playwright `Frame`.

4. **Frame-aware interaction.** Playwright locators do **not** cross iframe
   boundaries (unlike shadow DOM, which they pierce). Resolve an iframe-scoped
   ref through its frame — either `frame.locator('[data-ct-ref="N"]')` on the
   resolved `Frame`, or `page.frame_locator(...).locator(...)` chained for
   nesting. Both yield a `Locator` that the existing `human.py` interaction
   helpers accept, so mouse/keyboard simulation and coordinate translation keep
   working unchanged.

5. **Retire the dominant-frame switch.** Once every frame is in the merged view
   and refs resolve per-frame, `_detect_dominant_frame` / the `active_view`
   frame switch is redundant. Delete it. (Keep the fix that measures the real
   window via `window.innerWidth/innerHeight` if any viewport math survives.)

## Costs / risks to handle

- **N `evaluate` round-trips** instead of one. Parallelize with `gather`; gate
  to frames with real content and non-trivial size so ad/tracker iframes don't
  bloat output or latency.
- **Output budget.** Merged content can be large; the existing char budget and
  truncation must account for per-frame contributions.
- **Frame lifecycle.** Frames detach, reload, and navigate mid-flow, which
  invalidates stamped refs. Resolution must fail loudly ("re-run browse_page")
  when a frame is gone, matching the current stale-ref behavior.
- **Ordering with dynamically added iframes.** The placeholder-splice needs a
  stable way to match a walked `<iframe>` element to its Playwright `Frame`
  (e.g. stamp the element and correlate via `frame.frame_element()`).
- **Settle timing.** Each frame needs its own load/settle consideration before
  it's walked.

## Acceptance

The browser-tools suite covers dominant iframes today
(`test_dominant_*_iframe_becomes_the_page_view`, same + cross origin), which
must keep passing after the switch is removed. This work adds tests for the new
behavior, for both same- and cross-origin frames:

- a small (non-dominant) iframe's controls appear in the page view alongside the
  host page's content;
- multiple iframes on one page are all surfaced;
- `click`/`fill_field` reach controls inside a non-dominant iframe by ref.

The generic embed-host fixture already accepts a `width`/`height` to produce a
non-dominant iframe, so these tests need no new fixtures.
