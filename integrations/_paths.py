"""Shared path-prefix normalization for CLI-exec folder scoping.

Both the supervisor (storing/comparing a scope in metadata) and the
exec_broker (enforcing a scope against a caller-supplied cwd) need the same
canonical form, so that equivalent inputs (``"repo"``, ``"/repo/"``,
``" repo "``) are always treated as the same scope wherever they're
compared — a mismatch between the two would let two integrations that are
actually the same broker-enforced folder pass a same-scope collision check,
or leave an integration permanently unusable if a whitespace-only value
ever reaches the broker as a literal (unmatchable) directory name.
"""

from __future__ import annotations


def normalize_path_prefix(raw: str) -> str:
    """Strip whitespace, then slashes, leaving a clean relative-path fragment.

    Whitespace is stripped first so a value that's only whitespace (or only
    whitespace and slashes) collapses to ``""`` rather than surviving as a
    scope no real directory could ever match.
    """
    return raw.strip().strip("/")
