"""The allowlist of theme settings the app lets anyone change.

Each setting names an existing CSS token and carries that token's shipped
default for both modes. Anything not listed here cannot be written, which is
what keeps the supported surface to appearance only.
"""

from __future__ import annotations

from .types import SettingKind, ThemeSetting


def _color(setting_id: str, description: str, light: str, dark: str | None = None) -> ThemeSetting:
    return ThemeSetting(setting_id, "color", description, light, light if dark is None else dark)


def _font(setting_id: str, description: str, default: str) -> ThemeSetting:
    return ThemeSetting(setting_id, "font", description, default, default)


COLOR_SETTINGS: tuple[ThemeSetting, ...] = (
    # Surfaces
    _color("canvas", "Main page background", "#f8f9fb", "#0c0e14"),
    _color("surface", "Panel and card background", "#eef0f5", "#151821"),
    _color("elevated", "Raised surfaces such as modals and popovers", "#ffffff", "#1e2130"),
    # Text
    _color("text-primary", "Main text color", "#0f172a", "#e8ecf4"),
    _color("text-secondary", "Secondary and muted text", "#475569", "#8892a8"),
    _color("text-tertiary", "Faint and disabled text", "#94a3b8", "#4a5168"),
    _color("text-on-accent", "Text drawn on top of the accent color (for example on buttons)", "#ffffff"),
    # Borders
    _color("border", "Default border color", "#e2e8f0", "#252a3a"),
    _color("border-subtle", "Faint dividers", "#f1f5f9", "#1a1e2a"),
    _color("border-strong", "Emphasized borders", "#cbd5e1", "#363d52"),
    # Accent
    _color("accent", "Primary interactive color (buttons, links)", "#2563eb", "#3b82f6"),
    _color("accent-hover", "Accent-colored buttons and links while hovered", "#1d4ed8", "#60a5fa"),
    _color(
        "accent-muted",
        "Soft accent tint behind hovered, selected and active items (icon buttons, rows), badges and info panels",
        "rgba(37,99,235,0.08)",
        "rgba(59,130,246,0.12)",
    ),
    _color("accent-glow", "Accent glow around focus rings", "rgba(37,99,235,0.15)", "rgba(59,130,246,0.20)"),
    # Status
    _color("success", "Success color", "#16a34a", "#4ade80"),
    _color("success-muted", "Success background tint", "rgba(22,163,74,0.08)", "rgba(74,222,128,0.12)"),
    _color("warning", "Warning color", "#d97706", "#fbbf24"),
    _color("warning-muted", "Warning background tint", "rgba(217,119,6,0.08)", "rgba(251,191,36,0.12)"),
    _color("danger", "Error and danger color", "#dc2626", "#f87171"),
    _color("danger-muted", "Error background tint", "rgba(220,38,38,0.08)", "rgba(248,113,113,0.12)"),
    # Overlay
    _color("scrim", "Backdrop behind modals and dialogs", "rgba(15,23,42,0.40)", "rgba(0,0,0,0.60)"),
    # Terminal
    _color("terminal-bg", "Terminal panel background", "#edf1fb", "#111318"),
    _color("terminal-surface", "Terminal input and row background", "#e2e9f7", "#1a1d26"),
    _color("terminal-border", "Terminal panel border", "#c8d4ec", "#252a3a"),
    _color("terminal-text", "Terminal text", "#1e293b", "#c8cdd8"),
    _color("terminal-prompt", "Terminal prompt and stdout accent", "#16a34a", "#4ade80"),
    _color("terminal-stderr", "Terminal stderr text", "#dc2626", "#ff7043"),
    _color("terminal-comment", "Terminal comment and muted text", "#8898b5", "#4a5168"),
    # Syntax highlighting
    _color("code-keyword", "Code keywords", "#7c3aed", "#c792ea"),
    _color("code-function", "Code function names", "#1d4ed8", "#82aaff"),
    _color("code-string", "Code string literals", "#15803d", "#c3e88d"),
    _color("code-comment", "Code comments", "#8898b5", "#546e7a"),
    _color("code-number", "Code number literals", "#c2410c", "#f78c6c"),
    _color("code-operator", "Code operators", "#0e7490", "#89ddff"),
    _color("code-type", "Code type names", "#b45309", "#ffcb6b"),
)

FONT_SETTINGS: tuple[ThemeSetting, ...] = (
    _font(
        "font-brand",
        "Brand and logo typeface",
        "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    ),
    _font(
        "font-body",
        "Main UI text typeface",
        "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    ),
    _font("font-code", "Code and terminal typeface", "'JetBrains Mono', 'Fira Mono', 'Consolas', monospace"),
)

# Plain names callers tend to guess, mapped to the setting they most likely mean. They only
# power the "did you mean" suggestion in an error; an alias is never accepted as a setting id.
SETTING_ALIASES: dict[str, str] = {
    "background": "canvas",
    "background-color": "canvas",
    "bg": "canvas",
    "page": "canvas",
    "page-background": "canvas",
    "panel": "surface",
    "card": "surface",
    "modal": "elevated",
    "popover": "elevated",
    "text": "text-primary",
    "foreground": "text-primary",
    "primary": "accent",
    "link": "accent",
    "hover": "accent-hover",
    "font": "font-body",
    "body-font": "font-body",
    "code-font": "font-code",
}

_BY_KIND: dict[SettingKind, dict[str, ThemeSetting]] = {
    "color": {setting.id: setting for setting in COLOR_SETTINGS},
    "font": {setting.id: setting for setting in FONT_SETTINGS},
}


def settings_for(kind: SettingKind) -> dict[str, ThemeSetting]:
    """Return the settings of one kind, keyed by id."""
    return _BY_KIND[kind]
