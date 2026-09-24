"""Sharing user-generated content between omnideck installs.

Exports agent profiles and skills as portable, self-describing packs and
imports them back. A pack is the typed wire format; one import path handles
whatever a pack carries, so new shareable content types slot in here.
"""

from packs._pack import (
    PACK_KIND,
    PACK_VERSION,
    ImportSummary,
    Pack,
    PackedProfile,
    PackedSkill,
    build_profile_pack,
    build_skill_pack,
    import_pack,
)

__all__ = [
    "PACK_KIND",
    "PACK_VERSION",
    "ImportSummary",
    "Pack",
    "PackedProfile",
    "PackedSkill",
    "build_profile_pack",
    "build_skill_pack",
    "import_pack",
]
