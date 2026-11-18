"""The application wires goals into routes, the scheduler, the runtime and the activity stream."""

from goals import GoalRunExtension
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._goals import GOAL_STORE_KEY, GoalActivityFeed
from server._run_activity import ACTIVITY_FEEDS_KEY
from server._scheduling import SCHEDULER_KEY
from server.aiohttp_app import create_app


async def test_app_registers_goal_routes_and_the_goals_source(harness, tmp_path):
    app = create_app()
    try:
        paths = {resource.canonical for resource in app.router.resources()}
        assert "/api/conversations/sessions/{conversation_id}/goal" in paths
        assert "/api/goals" not in paths
        assert set(app[SCHEDULER_KEY]._sources) == {"goals"}
        assert [type(extension) for extension in app[AGENT_RUNTIME_KEY]._extensions] == [GoalRunExtension]
        assert [type(feed) for feed in app[ACTIVITY_FEEDS_KEY]] == [GoalActivityFeed]
        assert app[GOAL_STORE_KEY]._base == (tmp_path / "conversations").resolve()
    finally:
        await app[AGENT_RUNTIME_KEY].close()
