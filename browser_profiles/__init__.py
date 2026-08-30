"""Pure models and persistence for explicitly saved Browser profiles.

Runtime session coordination lives in dedicated modules so importing the store
from migrations does not register hooks or initialize Browser dependencies.
"""

from browser_profiles._models import BrowserProfile, BrowserProfileSite
from browser_profiles._store import BrowserProfileStore, get_browser_profile_store

__all__ = [
    "BrowserProfile",
    "BrowserProfileSite",
    "BrowserProfileStore",
    "get_browser_profile_store",
]
