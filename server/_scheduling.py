"""Application-owned scheduler shared by goals and routines."""
from aiohttp import web
from scheduling import Scheduler

SCHEDULER_KEY: web.AppKey[Scheduler] = web.AppKey("scheduler", Scheduler)
