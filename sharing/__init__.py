"""Sharing user-generated content between omnideck installs.

Exports agent profiles and skills as portable, self-describing bundles and
imports them back. A bundle is the typed wire format; one import path handles
whatever a bundle carries, so new shareable content types slot in here.
"""

from sharing._bundle import (
    BUNDLE_KIND,
    BUNDLE_VERSION,
    Bundle,
    ImportSummary,
    build_profile_bundle,
    build_skill_bundle,
    import_bundle,
)

__all__ = [
    "BUNDLE_KIND",
    "BUNDLE_VERSION",
    "Bundle",
    "ImportSummary",
    "build_profile_bundle",
    "build_skill_bundle",
    "import_bundle",
]
