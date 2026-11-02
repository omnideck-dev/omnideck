"""Whole-app theme overrides, stored as custom.css in the app home directory."""

from __future__ import annotations

import tempfile
from pathlib import Path

from config import load_config

DEFAULT_CUSTOM_CSS = """\
/* ═══════════════════════════════════════════════════════
   Theme overrides
   ═══════════════════════════════════════════════════════
   Loaded after the app's core styles, so anything you set
   here wins. Safe to edit by hand, or ask the agent to edit
   it for you (e.g. "make the accent color purple").

   Every variable below is commented out and set to its
   current default. Uncomment a line and change its value to
   override that piece of the theme. Leave it commented to
   keep the default. Edits take effect within a few seconds —
   no reload needed. */

/* ── Light mode ("Blueprint") ── */
:root {
  /* Surfaces */
  /* --canvas: #f8f9fb; */       /* Main page background */
  /* --surface: #eef0f5; */      /* Panel/card background */
  /* --elevated: #ffffff; */     /* Raised surface (modals, popovers) */

  /* Text */
  /* --text-primary: #0f172a; */   /* Main text color */
  /* --text-secondary: #475569; */ /* Secondary/muted text */
  /* --text-tertiary: #94a3b8; */  /* Faint/disabled text */

  /* Borders */
  /* --border: #e2e8f0; */         /* Default border color */
  /* --border-subtle: #f1f5f9; */  /* Faint dividers */
  /* --border-strong: #cbd5e1; */  /* Emphasized border */

  /* Accent (interactive) */
  /* --accent: #2563eb; */                    /* Primary interactive color (buttons, links) */
  /* --accent-hover: #1d4ed8; */              /* Accent color on hover */
  /* --accent-muted: rgba(37,99,235,0.08); */ /* Accent tint for subtle backgrounds */
  /* --accent-glow: rgba(37,99,235,0.15); */  /* Accent glow for focus rings */

  /* Status */
  /* --success: #16a34a; */                    /* Success color */
  /* --success-muted: rgba(22,163,74,0.08); */ /* Success background tint */
  /* --warning: #d97706; */                    /* Warning color */
  /* --warning-muted: rgba(217,119,6,0.08); */ /* Warning background tint */
  /* --danger: #dc2626; */                     /* Error/danger color */
  /* --danger-muted: rgba(220,38,38,0.08); */  /* Error background tint */

  /* Overlay */
  /* --scrim: rgba(15,23,42,0.40); */  /* Modal/dialog backdrop overlay */

  /* Shadows */
  /* --shadow-sm: 0 1px 2px rgba(15,23,42,0.05); */ /* Small elevation shadow */
  /* --shadow-md: 0 2px 8px rgba(15,23,42,0.08), 0 1px 2px rgba(15,23,42,0.04); */ /* Medium elevation shadow */
  /* --shadow-lg: 0 4px 16px rgba(15,23,42,0.10), 0 2px 4px rgba(15,23,42,0.05); */ /* Large elevation shadow */
  /* --shadow-glow: 0 0 0 3px var(--accent-glow); */ /* Focus-ring glow shadow */

  /* Terminal */
  /* --terminal-bg: #edf1fb; */        /* Terminal panel background */
  /* --terminal-surface: #e2e9f7; */   /* Terminal input/row background */
  /* --terminal-border: #c8d4ec; */    /* Terminal panel border */
  /* --terminal-text: #1e293b; */      /* Terminal text color */
  /* --terminal-prompt: #16a34a; */    /* Terminal prompt/stdout accent */
  /* --terminal-stderr: #dc2626; */    /* Terminal stderr color */
  /* --terminal-comment: #8898b5; */   /* Terminal comment/muted text */

  /* Syntax highlighting */
  /* --code-keyword: #7c3aed; */   /* Code keyword color */
  /* --code-function: #1d4ed8; */  /* Code function name color */
  /* --code-string: #15803d; */    /* Code string literal color */
  /* --code-comment: #8898b5; */   /* Code comment color */
  /* --code-number: #c2410c; */    /* Code number literal color */
  /* --code-operator: #0e7490; */  /* Code operator color */
  /* --code-type: #b45309; */      /* Code type name color */
}

/* ── Fonts (same in light and dark) ── */
:root {
  /* --font-brand: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; */ /* Brand/logo typeface */
  /* --font-body: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; */  /* Main UI body typeface */
  /* --font-code: 'JetBrains Mono', 'Fira Mono', 'Consolas', monospace; */               /* Code/terminal typeface */
}

/* ── Dark mode ("Terminal") ── */
[data-theme="dark"] {
  /* Surfaces */
  /* --canvas: #0c0e14; */       /* Main page background */
  /* --surface: #151821; */      /* Panel/card background */
  /* --elevated: #1e2130; */     /* Raised surface (modals, popovers) */

  /* Text */
  /* --text-primary: #e8ecf4; */   /* Main text color */
  /* --text-secondary: #8892a8; */ /* Secondary/muted text */
  /* --text-tertiary: #4a5168; */  /* Faint/disabled text */

  /* Borders */
  /* --border: #252a3a; */         /* Default border color */
  /* --border-subtle: #1a1e2a; */  /* Faint dividers */
  /* --border-strong: #363d52; */  /* Emphasized border */

  /* Accent (interactive) */
  /* --accent: #3b82f6; */                     /* Primary interactive color (buttons, links) */
  /* --accent-hover: #60a5fa; */               /* Accent color on hover */
  /* --accent-muted: rgba(59,130,246,0.12); */ /* Accent tint for subtle backgrounds */
  /* --accent-glow: rgba(59,130,246,0.20); */  /* Accent glow for focus rings */

  /* Status */
  /* --success: #4ade80; */                     /* Success color */
  /* --success-muted: rgba(74,222,128,0.12); */ /* Success background tint */
  /* --warning: #fbbf24; */                     /* Warning color */
  /* --warning-muted: rgba(251,191,36,0.12); */ /* Warning background tint */
  /* --danger: #f87171; */                      /* Error/danger color */
  /* --danger-muted: rgba(248,113,113,0.12); */ /* Error background tint */

  /* Overlay */
  /* --scrim: rgba(0,0,0,0.60); */  /* Modal/dialog backdrop overlay */

  /* Shadows */
  /* --shadow-sm: 0 1px 2px rgba(0,0,0,0.3); */ /* Small elevation shadow */
  /* --shadow-md: 0 2px 8px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.2); */ /* Medium elevation shadow */
  /* --shadow-lg: 0 4px 16px rgba(0,0,0,0.5), 0 2px 4px rgba(0,0,0,0.3); */ /* Large elevation shadow */
  /* --shadow-glow: 0 0 0 3px var(--accent-glow); */ /* Focus-ring glow shadow */

  /* Terminal */
  /* --terminal-bg: #111318; */       /* Terminal panel background */
  /* --terminal-surface: #1a1d26; */  /* Terminal input/row background */
  /* --terminal-border: #252a3a; */   /* Terminal panel border */
  /* --terminal-text: #c8cdd8; */     /* Terminal text color */
  /* --terminal-prompt: #4ade80; */   /* Terminal prompt/stdout accent */
  /* --terminal-stderr: #ff7043; */   /* Terminal stderr color */
  /* --terminal-comment: #4a5168; */  /* Terminal comment/muted text */

  /* Syntax highlighting */
  /* --code-keyword: #c792ea; */   /* Code keyword color */
  /* --code-function: #82aaff; */  /* Code function name color */
  /* --code-string: #c3e88d; */    /* Code string literal color */
  /* --code-comment: #546e7a; */   /* Code comment color */
  /* --code-number: #f78c6c; */    /* Code number literal color */
  /* --code-operator: #89ddff; */  /* Code operator color */
  /* --code-type: #ffcb6b; */      /* Code type name color */
}
"""


def custom_css_path() -> Path:
    """Location of the user's custom.css, alongside settings.json in the app home."""
    return Path(load_config().settings.home_dir) / "custom.css"


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file and replace, so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8") as f:
        f.write(text)
        tmp = Path(f.name)
    try:
        # Temp files are created owner-only; custom.css is meant to be hand-edited
        # too, so give it the same world-readable mode a plain write produces.
        tmp.chmod(0o644)
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def ensure_custom_css_file() -> None:
    """Seed custom.css with the commented-out default theme if it doesn't exist yet."""
    path = custom_css_path()
    if not path.exists():
        _write_atomic(path, DEFAULT_CUSTOM_CSS)


async def get_custom_css() -> dict[str, object]:
    """Read the app's custom theme stylesheet (custom.css).

    This one file themes the whole app, in both light and dark mode — it is not
    per-component styling. It ships with every overridable variable listed and
    commented out; only uncommented lines take effect.

    Call this before set_custom_css so you can edit the existing text rather
    than overwrite the user's earlier changes.

    Returns:
        A dict with status "ok" and the full stylesheet text under "css".
    """
    ensure_custom_css_file()
    return {"status": "ok", "css": custom_css_path().read_text(encoding="utf-8")}


async def set_custom_css(css: str) -> dict[str, object]:
    """Replace the app's custom theme stylesheet (custom.css) with new text.

    This changes the look of the whole app, in both light and dark mode — use it
    only for app-wide theme changes such as colors and fonts, never to style a
    single component. The entire file is replaced, so call get_custom_css first
    and send back the full edited text, keeping the user's existing overrides and
    comments. The change appears in the browser within a few seconds.

    Args:
        css: The complete new contents of custom.css.

    Returns:
        A dict with status "ok" and the number of characters written.
    """
    _write_atomic(custom_css_path(), css)
    return {"status": "ok", "length": len(css)}
