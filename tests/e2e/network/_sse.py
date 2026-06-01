"""Shared SSE envelope helpers for the network-view e2e tests.

The chat endpoint streams JSONL events with the shape
``{payload: {...}, agent_id, agent_name, timestamp, depth}``. The
``_evt`` helper here builds one such envelope; ``build_jsonl`` joins
many into the body the mock returns. Tests should always include the
``iteration`` events that production emits — without them the chat
side never materialises an assistant section, which silently masks
events-first regressions.
"""

from __future__ import annotations

import json


def _evt(payload: dict, *, agent_id: str, agent_name: str = "",
         depth: int = 0, ts: str = "2026-05-03T10:00:00+00:00") -> dict:
    return {
        "payload": payload,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "timestamp": ts,
        "depth": depth,
    }


def build_jsonl(events: list[dict]) -> str:
    return "".join(json.dumps(e) + "\n" for e in events)
