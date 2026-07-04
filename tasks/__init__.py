"""Autonomous task engine — persistent, background-executing routines.

Public API::

    from tasks import get_store

    store = get_store()  # lazily initialized on first call
"""

from __future__ import annotations

from tasks._executor import TaskExecutor
from tasks._file_store import ROUTINES_SUBDIR
from tasks._notifier import TelegramNotifier
from tasks._runner import TaskRunner
from tasks._singleton import get_store
from tasks._store import TaskStore
from tasks._tools import add_task, begin_routine, commit_routine, list_routines, list_tasks, trigger_routine

__all__ = [
    "ROUTINES_SUBDIR",
    "TaskExecutor",
    "TaskRunner",
    "TaskStore",
    "TelegramNotifier",
    "add_task",
    "begin_routine",
    "commit_routine",
    "get_store",
    "list_routines",
    "list_tasks",
    "trigger_routine",
]
