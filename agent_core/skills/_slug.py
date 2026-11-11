"""The chat-composer slug for a skill's display name."""

import re


def skill_slug(name: str) -> str:
    """Kebab-case a skill name into the token a user types after `/`.

    The composer computes the same slug client-side when it inserts a token,
    so the two must stay behaviorally identical.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
