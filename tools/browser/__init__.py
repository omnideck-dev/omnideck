"""Browser tools package.

Browser state persists between tool calls within its conversation or agent
scope. This includes cookies, localStorage/sessionStorage, and open tabs.
Call ``close_browser`` (or restart the process) to fully reset that state.

Public API:
- goto: Navigate an existing tab to a URL.
- new_tab: Open a new tab at a URL.
- close_tab: Close a tab; its ID is not reused.
- browse_page: Browse the current page (no navigation) with ``[role] name``
  markers for interactive elements.  Optional ``scope`` parameter to focus
  on a specific section.
- read_page: Read the current page as clean markdown text for reading
  articles, documentation, or search results.
- click, fill_field, press_keys, select_option, scroll_page, go_back, drag:
  Interaction tools that return a formatted rendered-document string.
- inspect_page: Visually inspect the current page and answer a question about it.
- browser_visual_action: Ask a vision model to decide and execute the next GUI
  action (click, type, scroll, drag, etc.).
- execute_javascript: Execute arbitrary JavaScript for advanced scenarios (use sparingly;
  prefer structured tools like click, fill_field for reliability).
- close_browser: Cleanly close the persistent Playwright browser.
"""

from .browse import browse_page
from .core.browser import Browser
from .core.exceptions import BrowserToolError
from .core.pool import close_browser, get_browser
from .core.rendering import RenderedDocument
from .core.tab import Tab
from .interactions import (
    click,
    drag,
    fill_field,
    press_and_hold,
    press_keys,
    scroll_page,
)
from .navigation import close_tab, go_back, goto, new_tab
from .read import read_page
from .save import save_page_content
from .scripting import execute_javascript
from .select import select_option
from .vision import (
    browser_visual_action,
    inspect_page,
)

__all__ = [
    "Browser",
    "BrowserToolError",
    "RenderedDocument",
    "Tab",
    "browse_page",
    "browser_visual_action",
    "click",
    "close_browser",
    "close_tab",
    "drag",
    "execute_javascript",
    "fill_field",
    "get_browser",
    "go_back",
    "goto",
    "inspect_page",
    "new_tab",
    "press_and_hold",
    "press_keys",
    "read_page",
    "save_page_content",
    "scroll_page",
    "select_option",
]
