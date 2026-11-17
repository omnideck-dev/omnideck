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
    to style one component. Light and dark mode have separate colors, so change
    both unless the user names one mode. Colors must be hex or rgb()/hsl()
    values and fonts plain font family names. The update is all-or-nothing: if
    any entry is invalid nothing is saved and the error lists every problem
    along with the valid setting names. The change reaches the open app within
    moments.

    Color setting ids, used under light and dark. Backgrounds: canvas (the page
    background), surface (panels and cards), elevated (modals and popovers),
    scrim (the dim layer behind dialogs). Text: text-primary, text-secondary,
    text-tertiary, text-on-accent (text on accent-colored buttons). Borders:
    border, border-subtle, border-strong. Accent (buttons, links, focus rings):
    accent, accent-hover, accent-muted, accent-glow. Status: success,
    success-muted, warning, warning-muted, danger, danger-muted (the -muted ones
    are background tints). Terminal: terminal-bg, terminal-surface,
    terminal-border, terminal-text, terminal-prompt, terminal-stderr,
    terminal-comment. Code highlighting: code-keyword, code-function,
    code-string, code-comment, code-number, code-operator, code-type. Font
    setting ids, used under fonts: font-body (UI text), font-code (code and
    terminal), font-brand (logo). Call get_theme for each setting's
    description, default and current value.

    Match the request. A whole look, palette or named style (a themed
    background, dark and moody) means setting backgrounds, text and borders
    together, in both modes, so text stays readable on the new backgrounds;
    changing only the accent would barely show. Change just the accent for
    requests about buttons, links or highlights. Call get_theme first when you
    are unsure which settings exist or what is already customized.

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
