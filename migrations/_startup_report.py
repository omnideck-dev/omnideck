"""Versioned, secret-free startup events consumed by the CLI and desktop.

Container logs survive an exited process. Timestamps let consumers reject
events from before the container's current StartedAt, including automatic
restarts. Only fixed status codes and migration identifiers cross this boundary.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import re
import sys

PREFIX = "OMNIDECK_STARTUP "
current_step: ContextVar[str] = ContextVar("migration_step", default="migration_history")


def _emit(status: str) -> None:
    step = current_step.get()
    if not re.fullmatch(r"[a-zA-Z0-9_:.-]{1,100}", step):
        step = "unknown"
    event = {
        "version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "status": status,
        "phase": "migrations",
        "step": step,
    }
    if status == "failed":
        event["code"] = "MIGRATION_FAILED"
    print(PREFIX + json.dumps(event), file=sys.stderr, flush=True)


@contextmanager
def report_migrations():
    """Report the migration barrier without serializing exception contents."""
    token = current_step.set("migration_history")
    _emit("starting")
    try:
        yield
    except Exception:
        _emit("failed")
        raise
    else:
        _emit("complete")
    finally:
        current_step.reset(token)
