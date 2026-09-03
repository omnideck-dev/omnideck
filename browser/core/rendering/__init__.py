"""Render selected browser documents into agent-readable data."""

from browser.core.rendering.model import RenderedDocument
from browser.core.rendering.renderer import DEFAULT_BUDGET, render_document

__all__ = ["DEFAULT_BUDGET", "RenderedDocument", "render_document"]
