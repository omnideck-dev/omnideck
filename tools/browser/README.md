# Browser tools

The browser package gives agents a stable, tab-oriented tool API while keeping
Playwright behind a small internal model:

```text
agent tool
   |
   v
Browser  -- owns the Chromium context and open tabs
   |
   v
Tab      -- stable tab ID, navigation, screenshots, selected document
   |
   v
Document -- DOM context plus the owning tab's physical input route
   |
   v
RenderedDocument  -- parsed, agent-readable content and interaction refs
```

The agent-facing tool signatures are the compatibility boundary. `Browser`,
`Tab`, and `Document` are free to evolve internally without changing how the
agent calls the tools or interprets their results.

## Agent tool surface

The package exports these tools from `tools.browser`:

| Area | Tools |
| --- | --- |
| Navigation | `goto`, `new_tab`, `close_tab`, `go_back` |
| DOM interaction | `click`, `press_and_hold`, `drag`, `fill_field`, `press_keys`, `select_option`, `scroll_page` |
| Page access | `browse_page`, `read_page`, `save_page_content` |
| Advanced access | `execute_javascript`, `inspect_page`, `browser_visual_action` |

Every agent tool has a Google-style docstring. Contract tests pin each tool's
parameters, defaults, keyword-only boundaries, and documentation sections.

Tab IDs are stable and monotonically allocated. Closing a tab never reuses its
ID, so a stale call fails instead of acting on a different tab. Tools include
`tab=N` in the page header and expect that value on later calls.

## Core model

### Browser

`core/browser.py` owns behavior that spans a browser context:

- launching and closing Chromium contexts;
- tracking every tab, including `target=_blank` and `window.open` tabs;
- assigning stable IDs;
- coordinating navigation and post-interaction state;
- capturing downloads and choosing the tab where an interaction ended.

`core/pool.py` owns process-, conversation-, and agent-scoped Browser
lifecycle. Keeping the pool separate prevents global lifecycle state from
leaking into the Browser abstraction.

### Tab

`core/tab.py` is the behavior boundary for a browser tab. It owns:

- the stable ID and underlying Playwright page;
- normalized tab events, screenshots, activation, and DevTools sessions;
- explicit navigation exclusion;
- challenge state;
- selection and caching of the document browser tools should use;
- construction of a document-consistent `RenderedDocument`.

Playwright's Page is not exposed to tool implementations. Package internals
that genuinely coordinate at the context level use a private accessor.

### Document

`core/document.py` hides an important Playwright split: DOM work belongs to a
Frame, while mouse and keyboard input belong to the owning Page. A Document
keeps both handles together. It resolves agent refs and owns the element
operations that use them, so Playwright locators and element handles do not
escape into tool implementations. `core/input/` contains the low-level
physical input algorithms used behind that boundary.

The root document is selected normally. A large, content-bearing iframe can be
selected when the outer page is only a host for an embedded application.
Challenge pages always select the root document so tools do not enter a
verification widget.

A Document object's identity is also its lifetime identity. Root navigation,
selected-iframe navigation, detachment, or a selection change replaces the
Document. Rendering checks that identity before returning refs and
retries once if navigation raced the DOM walk. No parallel generation counter
is required.

### RenderedDocument and refs

`core/rendering/renderer.py` walks the selected document once and creates a
`RenderedDocument`. The renderer emits structured nodes in DOM order, stamps actionable elements with
`data-ct-ref=N`, and records viewport state. `core/rendering/pipeline.py` applies
scope filtering, site filters, rendering, and the character budget in Python.

The agent sees lines such as:

```text
[3] [searchbox] Search
[4] [link] Result title
[5] [button] Add to cart
```

`Document.resolve_ref()` accepts the returned number and resolves it inside
the selected Document. If the document changed, the old stamped element is
absent and the tool tells the agent to call `browse_page()` for fresh refs.

## Interaction pipeline

A mutating tool follows one shared path:

```text
resolve Browser + Tab + Document
        |
resolve ref to an opaque Document element
        |
perform the element operation through Document
        |
Browser.coordinate_action()
  - observe navigation/new-tab/download signals
  - wait briefly for deferred navigation to start
  - wait for navigation commit when it did start
  - select the resulting Tab and Document
        |
settle selected Document
        |
build RenderedDocument, verify Document identity, format tool result
```

Settling happens at the render-return boundary, after Browser has determined
which tab and document the action produced. This avoids settling an old
document immediately before a navigation replaces it. The phases in
`core/settling.py` are:

1. document load;
2. web-font readiness;
3. a quiet DOM mutation window, including open shadow roots;
4. completion of short CSS animations.

Each phase has an independent cap and records diagnostic timings. Network-idle
is intentionally not used because analytics, polling, and streaming requests
can keep it busy long after useful content is ready.

`browse_page()` is the non-mutating reread path. It captures current state
without repeating the settle delay that mutating tools already paid. The
document identity check still protects its refs if navigation races the walk.

## Module map

```text
tools/browser/
  browse.py             annotated page access
  interactions.py       DOM interaction tools
  navigation.py         tab and history navigation tools
  read.py               Markdown reading, chunking, and search
  save.py               save page content
  scripting.py          JavaScript execution
  select.py             select-element interaction
  vision.py             screenshots and visual actions
  _visual_actions.py    internal visual-action dispatch
  _tool_context.py      per-call Browser, Tab, and Document resolution
  _tool_support.py      coordinated-action result formatting
  events.py             UI screenshots and tab-state events

  core/
    browser.py          browser-context orchestration
    launch.py           Chrome launch, UA, and init-script policy
    pool.py             scoped Browser lifecycle
    tab.py              stable tab behavior
    document.py         selected DOM and input routing
    settling.py         bounded document settling
    downloads.py        file detection and persistence
    challenges.py       anti-bot challenge detection
    formatting.py       agent-facing result formatting
    markdown.py         HTML-to-Markdown conversion

    input/
      pointer.py        mouse movement, clicks, holds, and drags
      keyboard.py       typing and key chords
      scroll.py         document scrolling

    rendering/
      model.py          RenderedDocument model
      renderer.py       DOM walk and RenderedDocument construction
      pipeline.py       structured-node rendering and budgets
      nodes.py          structured DOM node types
      filters/          site-specific rendering filters
```

## Tests

Fast unit tests live in `tests/unit/tools/browser`. They cover individual
policies and Playwright edge cases with focused stubs.

Real-browser tests live in `tests/browser_tools`. They import agent tools from
the public `tools.browser` surface and drive them against fixture pages in a
real headed Chrome. The fixture only supplies the Browser lifecycle and local
HTTP origins; page operations go through the same public tool functions used
by agents.

Run them with:

```bash
just test-browser-tools
```

The recipe always uses headed mode. When `xvfb-run` is available it allocates a
separate display; otherwise it uses the current display.
