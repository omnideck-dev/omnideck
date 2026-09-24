"""Browser domain models and profile persistence.

Runtime and Chromium-heavy APIs live in explicit public modules so importing
profile models during migrations has no execution-side effects.
"""

from browser.profile_store import (
    DEFAULT_BROWSER_PROFILE_ID,
    EMPTY_BROWSER_PROFILE_ID,
    BrowserProfileStore,
    summarize_browser_sites,
)
from browser.profiles import BrowserProfile, BrowserProfileSite

__all__ = [
    "BrowserProfile",
    "BrowserProfileSite",
    "BrowserProfileStore",
    "DEFAULT_BROWSER_PROFILE_ID",
    "EMPTY_BROWSER_PROFILE_ID",
    "summarize_browser_sites",
]
