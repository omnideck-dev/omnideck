"""Render selected browser documents into agent-readable data."""

from tools.browser.core.rendering.model import RenderedDocument
from tools.browser.core.rendering.renderer import DEFAULT_BUDGET, render_document

__all__ = ["DEFAULT_BUDGET", "RenderedDocument", "render_document"]
