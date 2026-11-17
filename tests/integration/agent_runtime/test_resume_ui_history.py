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


async def test_resume_defers_root_and_child_thinking_until_requested(harness, aiohttp_client):
    harness.profile('root', allow_spawn=True)
    harness.profile('child')
    root = reply('Delegating', calls=[call('spawn_agent', profile='child', agent_name='CHILD', instructions='Research')])
    root.message.thinking = 'Root reasoning résumé 🧭' * 2000
    child = reply('Child answer')
    child.message.thinking = 'Child reasoning' * 2000
    harness.provider.plan('root', root, reply('Final answer'))
    harness.provider.plan('child', child)
    await harness.run('root')
    persisted = load_events_jsonl('contract')
    expected = {e['id']: e['thinking'] for e in persisted if e['type'] == 'iteration' and e.get('thinking')}
    assert len(expected) == 2
    await harness.manager.conversations.evict_conversation('contract')
    app = web.Application()
    app[AGENT_RUNTIME_KEY] = harness.manager
    register_conversation_routes(app)
    client = await aiohttp_client(app)
    response = await client.post('/api/conversations/sessions/contract/resume')
    snapshot = await response.json()
    deferred = [e for e in snapshot['events'] if e.get('thinking_ref')]
    assert {e['id'] for e in deferred} == expected.keys()
    assert all(e['thinking'] is None for e in deferred)
    assert {e['depth'] for e in deferred} == {0, 1}
    for event in deferred:
        assert event['thinking_ref'] == {'conversationId': 'contract', 'eventId': event['id']}
    response = await client.post('/api/conversations/sessions/contract/thinking', json={'event_ids': list(expected)})
    assert response.status == 200
    assert response.headers['Content-Encoding'] == 'gzip'
    assert await response.json() == expected
    assert load_events_jsonl('contract') == persisted
    harness.provider.plan('root', reply('Continued'))
    await harness.run('root', message='Continue')
    assert any(message.get('thinking') == root.message.thinking for message in harness.provider.requests[-1]['messages'])
    for body, status in [({'event_ids': ['missing']}, 404), ({'event_ids': []}, 400), ({'event_ids': [None]}, 400), ({}, 400)]:
        response = await client.post('/api/conversations/sessions/contract/thinking', json=body)
        assert response.status == status
    response = await client.post('/api/conversations/sessions/missing/thinking', json={'event_ids': list(expected)})
    assert response.status == 404
