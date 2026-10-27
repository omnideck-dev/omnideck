"""Generate the stylesheet that applies saved overrides to the UI."""

from __future__ import annotations

import hashlib

from .registry import settings_for
from .types import ThemeOverrides, ThemeSetting

# The app's own dark block is `[data-theme="dark"]` and its light block is `:root`.
# A plain `:root` rule appended afterwards would also win in dark mode, so each
# mode is scoped to out-rank the block it overrides without relying on order.
_LIGHT_SELECTOR = ':root:not([data-theme="dark"])'
_DARK_SELECTOR = ':root[data-theme="dark"]'
_SHARED_SELECTOR = ":root"


def _block(selector: str, known: dict[str, ThemeSetting], values: dict[str, str]) -> str:
    # Walk the allowlist, not `values`, so only registered settings can ever be emitted.
    declarations = [f"  {setting.css_var}: {values[key]};" for key, setting in known.items() if key in values]
    if not declarations:
        return ""
    return f"{selector} {{\n" + "\n".join(declarations) + "\n}\n"


def render_css(overrides: ThemeOverrides) -> str:
    """Return the stylesheet for ``overrides``, or an empty string when nothing is overridden."""
    colors = settings_for("color")
    blocks = [
        _block(_LIGHT_SELECTOR, colors, overrides.light),
        _block(_DARK_SELECTOR, colors, overrides.dark),
        _block(_SHARED_SELECTOR, settings_for("font"), overrides.fonts),
    ]
    return "\n".join(block for block in blocks if block)


def css_version(css: str) -> str:
    """Short content hash that changes exactly when the rendered theme does."""
    return hashlib.sha256(css.encode("utf-8")).hexdigest()[:12]
