"""Render a selected browser document into agent-readable data.

Walks the DOM in document order, emitting structured node data that the
Python pipeline transforms into the annotated text format the agent expects.
Each interactive element is stamped with a ``data-ct-ref`` attribute and
rendered as ``[ref] [role] name``.  Pass the ref number to ``click()``,
``fill_field()``, and other interaction tools.

Design goals:
    * Single ``page.evaluate()`` round-trip for the entire DOM walk
    * Viewport-clipped by default to keep output small
    * Ref numbers assigned in document order for deterministic interaction
    * Optional scoping to narrow output to a page section
    * Character budget enforced in Python pipeline
"""

from __future__ import annotations

import asyncio
import logging
import time

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Response

from tools.browser.core.document import Document
from tools.browser.core.downloads import is_file_content_type
from tools.browser.core.rendering.model import RenderedDocument
from tools.browser.core.rendering.pipeline import render_nodes
from tools.browser.core.settling import SettleTimings
from tools.browser.core.tab import Tab

# URL extensions that indicate non-HTML content the renderer cannot handle.
_NON_HTML_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".webm",
        ".zip",
        ".gz",
        ".tar",
        ".bz2",
        ".xz",
        ".7z",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
    }
)


def _is_non_html_url(url: str) -> bool:
    """Check if a URL points to a non-HTML resource based on its extension."""
    path = url.split("?")[0].split("#")[0].lower()
    return any(path.endswith(ext) for ext in _NON_HTML_EXTENSIONS)


logger = logging.getLogger(__name__)

DEFAULT_BUDGET = 8000
MAX_NAME_LEN = 150


# ---------------------------------------------------------------------------
# JavaScript structured DOM traversal
# ---------------------------------------------------------------------------
# Executed through Document in a single evaluate() call. Accepts a params object:
#   { fullPage: boolean }
# Returns: { nodes: [...], viewport: { width, height, scroll_top, document_height } }
#
# Each interactive element is stamped with a data-ct-ref="N" attribute so
# Document can resolve the emitted refs through their stamped attributes.
#
# Emits structured node data — all formatting, scoping, deduplication,
# and budget enforcement happen in the Python rendering pipeline.

_DOM_WALK_JS = """
(params) => {
  const { fullPage } = params;
  const vh = window.innerHeight;
  const vw = window.innerWidth;

  // ---- Role mapping ----
  function getRole(el) {
    const tag = el.tagName;
    const explicitRole = el.getAttribute('role');
    if (explicitRole) {
      // A native form control (<input>/<textarea>/<select>) is always
      // interactive, so a non-interactive explicit role on it (e.g. role="form"
      // on an <input>) is bogus: ignore it and fall through to the implicit
      // role below so the field isn't hidden. Any other explicit role is kept.
      const isFormControl = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
      const ignoreExplicitRole = isFormControl && !INTERACTIVE.has(explicitRole);
      if (!ignoreExplicitRole) return explicitRole;
    }
    if (el.isContentEditable) return 'textbox';
    switch (tag) {
      case 'A': return el.hasAttribute('href') ? 'link' : null;
      case 'BUTTON': return 'button';
      case 'SELECT': return 'combobox';
      case 'TEXTAREA': return 'textbox';
      case 'INPUT': {
        const t = (el.getAttribute('type') || 'text').toLowerCase();
        const m = {
          text:'textbox', search:'searchbox', email:'textbox',
          password:'textbox', tel:'textbox', url:'textbox',
          number:'spinbutton', range:'slider', checkbox:'checkbox',
          radio:'radio', submit:'button', reset:'button', button:'button'
        };
        return m[t] || 'textbox';
      }
      case 'H1': case 'H2': case 'H3':
      case 'H4': case 'H5': case 'H6':
        return 'heading';
      case 'IMG': return 'img';
      case 'NAV': return 'navigation';
      case 'MAIN': return 'main';
      // A <summary> is the native toggle for its <details> disclosure; expose it
      // as a button so it gets a ref and click() can open the collapsed body.
      case 'SUMMARY':
        return (el.parentElement && el.parentElement.tagName === 'DETAILS') ? 'button' : null;
      default: return null;
    }
  }

  const INTERACTIVE = new Set([
    'link','button','textbox','searchbox','checkbox','radio',
    'combobox','spinbutton','slider','switch','tab','menuitem',
    'option','treeitem'
  ]);

  // Something the agent can act on: a native control, or an element carrying one
  // of the interactive roles above. Matching a bare [role] would also count roles
  // that do nothing (note, presentation, banner) and treat ordinary prose as if
  // it held a control. Matching no role at all would miss aria controls and let a
  // tabbable wrapper swallow them into a single ref.
  const INTERACTIVE_SEL = 'a[href], button, input, select, textarea,'
    + ' [contenteditable]:not([contenteditable="false"]),'
    + [...INTERACTIVE].map(r => ' [role="' + r + '"]').join(',');

  function hasInteractive(el) {
    return el.querySelector(INTERACTIVE_SEL) !== null;
  }

  function isNativeInteractiveElement(el) {
    return el.matches(
      'a[href], button, input, select, textarea, summary,'
      + ' [contenteditable]:not([contenteditable="false"])'
    );
  }

  // ---- Accessible name ----
  function getName(el) {
    const al = el.getAttribute('aria-label');
    if (al) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const ref = document.getElementById(lb);
      if (ref) return (ref.innerText || ref.textContent || '').trim();
    }
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      const id = el.getAttribute('id');
      if (id) {
        const lbl = document.querySelector('label[for="' + id + '"]');
        if (lbl) return lbl.textContent.trim();
      }
      const wrappingLabel = el.closest('label');
      if (wrappingLabel) {
        let labelText = '';
        for (const node of wrappingLabel.childNodes) {
          if (node.nodeType === 3) labelText += node.textContent;
          else if (node !== el && node.nodeType === 1 && !['INPUT','TEXTAREA','SELECT'].includes(node.tagName))
            labelText += (node.innerText || node.textContent || '');
        }
        labelText = labelText.trim();
        if (labelText) return labelText;
      }
      const ph = el.getAttribute('placeholder');
      if (ph) return ph.trim();
      if (tag === 'INPUT') {
        const val = el.getAttribute('value');
        if (val) return val.trim();
      }
    }
    if (tag === 'SELECT') return '';
    if (tag === 'IMG') return (el.getAttribute('alt') || '').trim();
    const t = el.innerText;
    if (t && t.trim()) return t.trim();
    // Fall back to the title attribute — a valid low-priority accessible-name
    // source (the tooltip), used only when nothing else names the element. This
    // is what names icon-only controls with no text/aria-label, e.g.
    // <button title="Search"><svg>…</svg></button>.
    const title = el.getAttribute('title');
    if (title && title.trim()) return title.trim();
    // SVG icons often carry their label in a nested <title> instead.
    const svgTitle = el.querySelector('svg title');
    if (svgTitle && svgTitle.textContent && svgTitle.textContent.trim())
      return svgTitle.textContent.trim();
    return '';
  }

  // ---- Inline text containers ----
  const INLINE_TAGS = new Set([
    'B','STRONG','EM','I','U','S','SMALL','MARK','ABBR','CITE',
    'CODE','DFN','KBD','SAMP','VAR','SUB','SUP','SPAN','BDI','BDO',
    'DATA','TIME','Q','WBR','BR','DEL','INS','RUBY','RP','RT','FONT'
  ]);
  function isTextContainer(el) {
    if (el.shadowRoot) return false;
    if (el.children.length === 0) return false;
    if (hasInteractive(el)) return false;
    for (const child of el.children) {
      if (!INLINE_TAGS.has(child.tagName)) return false;
    }
    return true;
  }

  // ---- Implicit interactivity ----
  function isImplicitlyInteractive(el) {
    const tag = el.tagName;
    if (tag === 'BODY' || tag === 'HTML') return false;
    if (hasInteractive(el)) return false;
    if (el.shadowRoot && el.shadowRoot.querySelector(INTERACTIVE_SEL)) return false;
    const ti = el.getAttribute('tabindex');
    if (ti !== null && ti !== '-1') return true;
    const s = window.getComputedStyle(el);
    if (s.cursor === 'pointer') {
      const parent = el.parentElement;
      if (parent) {
        const ps = window.getComputedStyle(parent);
        if (ps.cursor === 'pointer') return false;
      }
      const text = (el.innerText || '').trim();
      if (text.length > 0 && text.length < 80) return true;
      if (el.querySelector('img, svg, canvas')) return true;
    }
    return false;
  }

  // ---- Visibility / viewport ----
  const scrolled = window.scrollY > 50;

  function shouldSkip(el) {
    if (el.getAttribute('aria-hidden') === 'true') {
      if (el.querySelector('[role="dialog"],[role="alertdialog"],dialog'))
        return 'skip-self';
      return 'skip-tree';
    }
    const s = window.getComputedStyle(el);
    if (s.display === 'none') return 'skip-tree';
    if (s.visibility === 'hidden') return 'skip-self';
    if (parseFloat(s.opacity) === 0
        && !(el.tagName === 'INPUT' && el.type === 'range'))
      return 'skip-self';
    if (scrolled && (s.position === 'sticky' || s.position === 'fixed')) {
      if (s.position === 'fixed') {
        const role = el.getAttribute('role');
        if (role === 'dialog' || role === 'alertdialog') return null;
        const r = el.getBoundingClientRect();
        if (r.width > vw * 0.5 && r.height > vh * 0.5) return null;
      }
      return 'skip-tree';
    }
    return null;
  }

  // Is this element itself on screen? Looks only at the element's own geometry,
  // and says nothing about its descendants: a box does not bound its content,
  // since out-of-flow (absolute / fixed) or overflow-scrolled children render
  // outside it. So the walk never prunes a subtree on this answer — an off-screen
  // element is still descended into, and each descendant is judged on its own
  // rect. This only decides whether to emit THIS element.
  function onScreen(el) {
    if (fullPage) return true;
    const r = el.getBoundingClientRect();
    // Zero-area, or outside the viewport rectangle: not on screen itself.
    if (!(r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw)) return false;
    // On screen by coordinates, but scrolled out of a clipping ancestor's box.
    let ancestor = el.parentElement;
    while (ancestor && ancestor !== document.body) {
      const os = window.getComputedStyle(ancestor);
      const clipX = os.overflowX === 'hidden' || os.overflowX === 'clip';
      const clipY = os.overflowY === 'hidden' || os.overflowY === 'clip';
      if (clipX || clipY) {
        const ar = ancestor.getBoundingClientRect();
        if (clipX && (r.right <= ar.left || r.left >= ar.right)) return false;
        if (clipY && (r.bottom <= ar.top || r.top >= ar.bottom)) return false;
      }
      ancestor = ancestor.parentElement;
    }
    return true;
  }

  const SKIP_ROLES = new Set(['separator']);

  // Structural container tags that emit container_start/container_end
  const CONTAINER_TAGS = new Set([
    'TABLE','THEAD','TBODY','TFOOT','TR','UL','OL','DL',
    'DETAILS','DIALOG','FIELDSET'
  ]);

  // ---- Ref counter ----
  let refCounter = 0;

  // Clean up exactly the elements stamped by the previous rendering. Keeping
  // direct element references covers shadow DOM without scanning the whole tree;
  // detached elements remain safe to clean and are released when the registry
  // is replaced below.
  const refRegistryKey = Symbol.for('omnideck.browser.refElements');
  const previousRefs = window[refRegistryKey];
  if (Array.isArray(previousRefs)) {
    for (const el of previousRefs) el.removeAttribute('data-ct-ref');
  }
  const currentRefs = [];
  window[refRegistryKey] = currentRefs;

  // ---- Output ----
  const nodes = [];
  let depth = 0;

  function emit(node) { nodes.push(node); }

  function clip(text) {
    return text.length > 200 ? text.substring(0, 200) + '...' : text;
  }

  // Collapse a block into one node — unless it holds something interactive, in
  // which case descend so the control gets its own ref. Doing both would print
  // the block's words once as the block and again as its parts.
  function collapseOrDescend(el, makeNode) {
    if (hasInteractive(el)) {
      walkChildren(el);
      return;
    }
    const text = (el.innerText || '').trim();
    if (text.length > 1) emit(makeNode(text));
  }

  // Walk the child nodes of a container (element or shadow root).
  function walkChildren(container) {
    const hasMixed = container.childNodes.length > container.children.length;
    if (hasMixed) {
      for (const child of container.childNodes) {
        if (child.nodeType === 3) {
          const text = child.textContent.trim();
          if (text.length > 1) {
            emit({ type: 'text', depth: depth, text: clip(text)});
          }
        } else if (child.nodeType === 1) {
          walkSlotOrElement(child);
        }
      }
    } else {
      for (const child of container.children) {
        walkSlotOrElement(child);
      }
    }
  }

  function walkSlotOrElement(el) {
    if (el.tagName === 'SLOT') {
      try {
        const assigned = el.assignedNodes();
        if (assigned.length > 0) {
          for (const node of assigned) {
            if (node.nodeType === 3) {
              const text = node.textContent.trim();
              if (text.length > 1) {
                emit({ type: 'text', depth: depth, text: clip(text)});
              }
            } else if (node.nodeType === 1) {
              walk(node, false);
            }
          }
        } else {
          walkChildren(el);
        }
      } catch (_e) { /* slot traversal failed */ }
    } else {
      walk(el, false);
    }
  }

  function walk(el, isRoot) {
    // Slot forwarding for double-nested shadow DOM (e.g. Reddit)
    if (el.tagName === 'SLOT') { walkSlotOrElement(el); return; }

    const skip = shouldSkip(el);
    if (skip === 'skip-tree') return;
    if (skip === 'skip-self') {
      for (const child of el.children) walk(child, false);
      return;
    }

    if (!isRoot && !onScreen(el)) {
      // Off screen itself, but its box may not bound its content: a descendant
      // laid out of flow (absolute / fixed) or inside an overflow-scroll region
      // can still be on screen. Descend and judge each child on its own rect
      // rather than pruning the subtree. Off-screen descendants are likewise not
      // emitted, so the visible result is unchanged; only content that was being
      // lost behind a mis-measured wrapper now surfaces.
      for (const child of el.children) walk(child, false);
      return;
    }

    const role = getRole(el);

    if (role && SKIP_ROLES.has(role)) return;

    // Interactive elements: stamp with ref, emit node data
    if (role && INTERACTIVE.has(role)) {
      // Widget libraries sometimes put an interactive role on a container that
      // wraps the real controls. Native controls are atomic, but a non-native
      // ARIA wrapper must step aside or its early return hides every actionable
      // descendant beneath it.
      if (!isNativeInteractiveElement(el) && hasInteractive(el)) {
        walkChildren(el);
        return;
      }

      let name = getName(el);
      if (!name && role !== 'combobox' && el.tagName !== 'SELECT') return;

      refCounter++;
      el.setAttribute('data-ct-ref', String(refCounter));
      currentRefs.push(el);

      const node = { type: 'interactive', depth: depth, ref: refCounter, role: role, name: name || ''};

      if (role === 'combobox' || el.tagName === 'SELECT') {
        const sel = el.selectedOptions?.[0] || el.querySelector('option[selected]');
        // For <input role="combobox"> (autocomplete widgets), fall back to
        // el.value since child <option> elements won't exist.
        node.value = sel ? sel.textContent.trim()
                         : (el.value != null && el.value !== '') ? String(el.value) : '';
      } else if (role === 'checkbox' || role === 'radio' || role === 'switch') {
        node.checked = el.checked || el.getAttribute('aria-checked') === 'true';
      } else if (role === 'textbox' || role === 'searchbox' || role === 'spinbutton' || role === 'slider') {
        node.value = (el.value != null && el.value !== '') ? String(el.value) : '';
        if (role === 'slider') {
          node.extra = {
            min: parseFloat(el.min) || 0,
            max: parseFloat(el.max) || 100,
            width: Math.floor(el.getBoundingClientRect().width)
          };
        }
      }

      // ARIA state annotations
      const pressed = el.getAttribute('aria-pressed');
      if (pressed === 'true') node.pressed = true;
      const expanded = el.getAttribute('aria-expanded');
      if (expanded === 'true') node.expanded = true;
      else if (expanded === 'false') node.expanded = false;
      const selected = el.getAttribute('aria-selected');
      if (selected === 'true') node.selected = true;
      // A <summary>'s open/closed state lives on its parent <details>, not on an
      // aria-expanded attribute — surface it so the agent knows whether to click.
      if (el.tagName === 'SUMMARY' && el.parentElement && el.parentElement.tagName === 'DETAILS') {
        node.expanded = el.parentElement.open;
      }

      emit(node);
      return;
    }

    // Implicitly interactive elements (cursor:pointer, tabindex, etc.)
    if (isImplicitlyInteractive(el)) {
      let name = (el.innerText || '').trim();
      if (!name || name.length >= 80) {
        const img = el.querySelector('img[alt]');
        if (img) name = (img.getAttribute('alt') || '').trim();
      }
      if (!name) name = el.getAttribute('aria-label') || el.dataset?.image || el.dataset?.name || '';
      if (name && name.length < 80) {
        refCounter++;
        el.setAttribute('data-ct-ref', String(refCounter));
        currentRefs.push(el);
        el.setAttribute('role', 'button');
        el.setAttribute('aria-label', name);
        emit({ type: 'interactive', depth: depth, ref: refCounter, role: 'button', name: name});
        return;
      }
    }

    // Headings
    if (role === 'heading') {
      // A heading can wrap a control: an <h3> whose title is a link, an <h5>
      // around a button. Then the control is what matters, not the label.
      const lvl = parseInt(el.tagName.match(/H(\\d)/)?.[1]) || null;
      collapseOrDescend(el, (text) => (
        { type: 'heading', depth: depth, name: text, level: lvl}
      ));
      return;
    }

    // Images
    if (role === 'img') {
      const alt = (el.getAttribute('alt') || el.getAttribute('aria-label') || '').trim();
      if (alt) emit({ type: 'image', depth: depth, name: alt});
      return;
    }

    // Structural containers
    if (CONTAINER_TAGS.has(el.tagName)) {
      emit({ type: 'container_start', depth: depth, tag: el.tagName.toLowerCase()});
      depth++;
      walkChildren(el);
      depth--;
      emit({ type: 'container_end', depth: depth, tag: el.tagName.toLowerCase()});
      return;
    }

    // Leaf text node
    if (el.children.length === 0 && !el.shadowRoot) {
      const text = (el.innerText || '').trim();
      if (text && text.length > 1) {
        emit({ type: 'text', depth: depth, text: clip(text)});
      }
      return;
    }

    // Paragraph-like containers
    if (el.tagName === 'P' || el.tagName === 'BLOCKQUOTE' || el.tagName === 'FIGCAPTION') {
      collapseOrDescend(el, (text) => ({ type: 'text', depth: depth, text: clip(text)}));
      return;
    }

    // Inline-only containers
    if (isTextContainer(el)) {
      const text = (el.innerText || '').trim();
      if (text && text.length > 1) {
        emit({ type: 'text', depth: depth, text: clip(text)});
      }
      return;
    }

    // Recurse into children / shadow DOM
    if (el.shadowRoot) {
      try { walkChildren(el.shadowRoot); }
      catch (_e) { walkChildren(el); }
    } else {
      walkChildren(el);
    }
  }

  walk(document.body, true);

  return {
    nodes: nodes,
    viewport: {
      width: Math.floor(vw),
      height: Math.floor(vh),
      scroll_top: Math.floor(window.scrollY),
      document_height: Math.floor(
        Math.max(
          document.scrollingElement?.scrollHeight || 0,
          document.body?.scrollHeight || 0
        )
      )
    }
  };
}
"""


async def render_document(
    tab: Tab,
    document: Document,
    response: Response | None,
    *,
    scope: str | None = None,
    budget: int = DEFAULT_BUDGET,
    full_page: bool = False,
    settle_timings: SettleTimings | None = None,
) -> RenderedDocument:
    """Render one selected document into immutable agent-readable data.

    Args:
        tab: Tab whose metadata identifies the returned page.
        document: Selected root or embedded document to walk.
        response: Navigation response (may be ``None``).
        scope: Optional section name to scope to (matches headings/landmarks).
        budget: Character budget for the content field.
        full_page: When True, include off-screen nodes in the rendering.
        settle_timings: Diagnostic timings collected before the DOM walk.

    Returns:
        ``RenderedDocument`` with annotated content, title, url, viewport info.
    """
    status_code = response.status if response is not None else None
    final_url = response.url if response is not None else tab.url
    dom_walk_ms = 0.0
    render_ms = 0.0
    node_count = 0

    # Detect non-HTML content (PDF, images, etc.) before attempting JS evaluate
    # which would hang indefinitely on pages without a normal DOM.
    _non_html = False
    if response is not None:
        ct = getattr(response, "headers", {}).get("content-type", "")
        if ct and is_file_content_type(ct):
            _non_html = True
            logger.debug("Non-HTML content-type detected: %s", ct)
    if not _non_html and _is_non_html_url(tab.url):
        _non_html = True
        logger.debug("Non-HTML URL extension detected: %s", tab.url)

    content = ""
    truncated = False
    viewport_data: dict[str, int] | None = None

    # A blocked document renders as its banner, and a non-HTML file renders as a
    # canned message. Neither has useful DOM content, so both skip the walk.
    if tab.challenge:
        content = tab.challenge.banner
    elif _non_html:
        _ext = tab.url.split("?")[0].rsplit(".", 1)[-1].lower() if "." in tab.url else "file"
        content = (
            f"[This is a {_ext.upper()} file, not a web page: {tab.url}]\n"
            "The browser cannot display this content. Use go_back() to return "
            "to the previous page. If you need this file, download it with "
            "run_bash_cmd and curl/wget."
        )
    else:
        try:
            t0 = time.monotonic()
            raw_result = await asyncio.wait_for(
                document.evaluate(
                    _DOM_WALK_JS,
                    {"fullPage": full_page},
                ),
                timeout=15,
            )
            t_js = time.monotonic()

            raw_nodes = raw_result.get("nodes", [])
            raw_viewport = raw_result.get("viewport", {})

            viewport_data = {
                "scroll_top": raw_viewport.get("scroll_top", 0),
                "viewport_height": raw_viewport.get("height", 800),
                "viewport_width": raw_viewport.get("width", 1280),
                "document_height": raw_viewport.get("document_height", 0),
            }

            content, truncated = render_nodes(
                raw_nodes,
                url=tab.url,
                scope_query=scope,
                budget=budget,
                name_limit=MAX_NAME_LEN,
            )
            t_py = time.monotonic()

            dom_walk_ms = (t_js - t0) * 1000
            render_ms = (t_py - t_js) * 1000
            node_count = len(raw_nodes)
        except TimeoutError:
            logger.warning("DOM walk timed out for %s (may be non-HTML content)", tab.url)
            content = (
                f"[Page content unavailable — document rendering timed out: {tab.url}]\n"
                "This may be a PDF or non-HTML document. Use go_back() to return "
                "to the previous page. If you need this file, download it with "
                "run_bash_cmd and curl/wget."
            )
        except PlaywrightError as exc:  # pragma: no cover - defensive
            logger.warning("Failed to render annotated document: %s", exc)
            content = (
                f"[Page content unavailable — document rendering failed: {tab.url}]\n"
                "The page may still be loading or changing. Try browse_page() again. "
                "If the problem continues, use read_page() to read the page "
                "without interactive refs."
            )

    return RenderedDocument(
        title=await tab.title(),
        url=final_url,
        status_code=status_code,
        content=content,
        viewport=viewport_data,
        truncated=truncated,
        settle_timings=settle_timings,
        dom_walk_ms=dom_walk_ms,
        render_ms=render_ms,
        node_count=node_count,
    )


__all__ = [
    "render_document",
]
