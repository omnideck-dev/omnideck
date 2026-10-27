"""Verify lightweight UI restores preserve durable model context."""

import base64
import gzip
import json
import random

from aiohttp import web

from conversations import load_events_jsonl
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._conversation_routes import register_conversation_routes

from ._support import call, reply


async def test_resume_omits_large_tool_results_but_next_turn_keeps_model_context(harness, aiohttp_client):
    # High-entropy output catches regressions that repetitive fixture text hides
    # behind compression, such as large search responses or embedded images.
    output = base64.b64encode(random.Random(42).randbytes(32 * 1024)).decode()

    async def lookup() -> str:
        """Return the requested reference material."""
        return output

    harness.skill("lookup", lookup)
    harness.profile(skills=["lookup"], context_window=1_000_000)
    harness.provider.plan("leaf", reply(calls=[call("lookup")]), reply("Saved answer"))
    await harness.run(message="Look up the reference")
    persisted = load_events_jsonl("contract")
    results = [event for event in persisted if event["type"] == "tool_result"]
    assert len(results) == 1
    assert output in results[0]["content"]

    # Force a cold restore as well as a warm one; neither may seed model history
    # from the smaller representation sent to the browser.
    await harness.manager.conversations.evict_conversation("contract")
    app = web.Application()
    app[AGENT_RUNTIME_KEY] = harness.manager
    register_conversation_routes(app)
    client = await aiohttp_client(app, auto_decompress=False)
    for _ in range(2):
        response = await client.post(
            "/api/conversations/sessions/contract/resume", headers={"Accept-Encoding": "gzip"},
        )
        assert response.status == 200
        assert response.headers["Content-Encoding"] == "gzip"
        compressed = await response.read()
        snapshot = json.loads(gzip.decompress(compressed))
        assert snapshot["events"] == [event for event in persisted if event["type"] != "tool_result"]
        previous_payload = {**snapshot, "events": persisted}
        previous_compressed = gzip.compress(json.dumps(previous_payload).encode())
        assert len(compressed) < len(previous_compressed) / 20
        assert load_events_jsonl("contract") == persisted

    harness.provider.plan("leaf", reply("Continued using the reference"))
    await harness.run(message="Continue from that reference")
    tool_messages = [message for message in harness.provider.requests[-1]["messages"] if message["role"] == "tool"]
    assert any(output in message["content"] for message in tool_messages)
