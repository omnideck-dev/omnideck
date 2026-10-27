"""Agent-facing adapters over the shared theme subsystem."""

from __future__ import annotations

from theme import ThemeError, get_theme_state, update_theme


async def get_theme() -> dict[str, object]:
    """Read the app's theme settings: what can be changed, the defaults, and what is currently set.

    The theme covers the whole app in both light and dark mode, never a single
    component. Colors are listed once per setting with separate light and dark
    values; fonts apply to both modes. For every setting you get its default, the
    saved override (null when unchanged) and the effective value actually in use.

    Call this before set_theme to learn the setting ids and to see what the user
    has already customized.

    Returns:
        A dict with status "ok", "colors" and "fonts" lists describing every
        supported setting, "overrides" with only the saved changes, and
        "value_formats" explaining what values each kind accepts.
    """
    return {"status": "ok", **get_theme_state()}


async def set_theme(
    light: dict | None = None,
    dark: dict | None = None,
    fonts: dict | None = None,
    reset: bool = False,
) -> dict[str, object]:
    """Change the app's colors or fonts. Settings you leave out keep their current value.

    Use this only when the user asks to change the look of the whole app, never
    to style one component. Only the settings listed by get_theme can be changed;
    values are checked by type, so colors must be hex or rgb()/hsl() values and
    fonts must be plain font family names. The change reaches the open app
    within moments.

    The update is all-or-nothing: if any entry is invalid nothing is saved and
    the error lists every problem. Light and dark colors are separate, so change
    both when the user wants the same color in either mode. A color often has
    related settings (for example accent, accent-hover, accent-muted and
    accent-glow) that you may want to change together.

    Args:
        light: Light-mode colors as {setting id: color}, e.g. {"accent": "#7c3aed"}. A null value clears that override.
        dark: Dark-mode colors in the same form as light.
        fonts: Fonts as {setting id: font list}, e.g. {"font-body": "'Segoe UI', sans-serif"}. A null value clears that override.
        reset: If true, every saved override is cleared first, so with no other arguments this restores the default theme and with values it replaces the whole theme.

    Returns:
        A dict with status "ok" and the full set of saved "overrides" after the change, or status "error" and an "error" message listing what was invalid.
    """
    try:
        return {"status": "ok", **update_theme(light=light, dark=dark, fonts=fonts, reset=reset)}
    except ThemeError as exc:
        return {"status": "error", "error": str(exc)}
