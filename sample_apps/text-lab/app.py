"""Backend actions for the Text Lab sample folder app."""

from __future__ import annotations

import re


def analyze(text: str) -> dict[str, int]:
    """Return a few deterministic text statistics."""
    words = re.findall(r"\b[\w'-]+\b", text)
    sentences = re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", text.strip()) if text.strip() else []
    return {
        "characters": len(text),
        "characters_without_spaces": len(re.sub(r"\s", "", text)),
        "words": len(words),
        "sentences": len(sentences),
        "reading_seconds": max(1, round(len(words) / 200 * 60)) if words else 0,
    }


def transform(text: str, mode: str) -> dict[str, str]:
    """Apply one simple transformation and return the new text."""
    transforms = {
        "uppercase": str.upper,
        "lowercase": str.lower,
        "title": str.title,
        "collapse": lambda value: re.sub(r"\s+", " ", value).strip(),
    }
    operation = transforms.get(mode)
    if operation is None:
        raise ValueError(f"Unsupported transform mode: {mode}")
    return {"text": operation(text)}


actions = {
    "analyze": analyze,
    "transform": transform,
}
