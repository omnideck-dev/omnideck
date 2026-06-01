"""E2E test for agent network persistence across turns.

Verifies that agent cards from a previous turn persist in the network
view when a second turn spawns new agents.
"""

from playwright.sync_api import Page, Route, expect

from tests.e2e.network._sse import _evt, build_jsonl
from tests.e2e.pages import ChatView, NetworkView


def _turn(root: str, sub_specs: list[tuple[str, str]],
          user_text: str, base_offset: int) -> str:
    """Build one root-+-N-subs turn. ``sub_specs`` is a list of
    ``(agent_id, agent_name)`` pairs."""
    def ts(n: int) -> str:
        return f"2026-05-03T10:0{base_offset}:{n:02d}+00:00"

    events: list[dict] = [
        _evt({"type": "agent_started", "agent_id": root,
              "agent_name": "computron", "parent_agent_id": None},
             agent_id=root, agent_name="computron", ts=ts(0)),
        _evt({"type": "user_message", "content": user_text,
              "attachments": [], "is_nudge": False},
             agent_id=root, agent_name="computron", ts=ts(1)),
    ]
    for i, (sid, sname) in enumerate(sub_specs, start=2):
        events.append(_evt(
            {"type": "agent_started", "agent_id": sid,
             "agent_name": sname, "parent_agent_id": root},
            agent_id=sid, agent_name=sname, depth=1, ts=ts(i),
        ))
    for i, (sid, sname) in enumerate(sub_specs, start=10):
        events.extend([
            _evt({"type": "content", "content": f"{sname} done."},
                 agent_id=sid, agent_name=sname, depth=1, ts=ts(i)),
            _evt({"type": "iteration", "iteration_index": 0,
                  "content": f"{sname} done.", "thinking": None,
                  "tool_calls": []},
                 agent_id=sid, agent_name=sname, depth=1, ts=ts(i)),
            _evt({"type": "agent_completed", "agent_id": sid,
                  "agent_name": sname, "status": "success"},
                 agent_id=sid, agent_name=sname, depth=1, ts=ts(i)),
        ])
    events.extend([
        _evt({"type": "content", "content": f"{user_text} complete."},
             agent_id=root, agent_name="computron", ts=ts(50)),
        _evt({"type": "iteration", "iteration_index": 0,
              "content": f"{user_text} complete.", "thinking": None,
              "tool_calls": []},
             agent_id=root, agent_name="computron", ts=ts(50)),
        _evt({"type": "agent_completed", "agent_id": root,
              "agent_name": "computron", "status": "success"},
             agent_id=root, agent_name="computron", ts=ts(51)),
        _evt({"type": "turn_end"},
             agent_id=root, agent_name="computron", ts=ts(52)),
    ])
    return build_jsonl(events)


TURN_1_EVENTS = _turn(
    "root1", [("t1_sub1", "research_agent")],
    user_text="turn 1", base_offset=0,
)
TURN_2_EVENTS = _turn(
    "root2",
    [("t2_sub1", "code_expert"), ("t2_sub2", "creative_writer")],
    user_text="turn 2", base_offset=1,
)


def test_cards_persist_across_turns(page: Page):
    """Cards from turn 1 remain visible after turn 2 adds new agents."""
    chat = ChatView(page).goto().new_conversation()
    turn = [1]

    def mock_chat(route: Route):
        body = TURN_1_EVENTS if turn[0] == 1 else TURN_2_EVENTS
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body,
        )

    page.route("**/api/chat", mock_chat)

    # Turn 1: root + research_agent
    chat.send("turn 1")
    chat.wait_streaming()

    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=5000)
    expect(network.indicator).to_contain_text("2 agents")

    # Turn 2: root + code_expert + creative_writer
    turn[0] = 2
    chat.send("turn 2")
    chat.wait_streaming()

    # Both trees are visible: turn 1 tree (2 cards) + turn 2 tree (3 cards)
    expect(network.indicator).to_contain_text("5 agents")

    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)
    assert network.agent_cards.count() == 5

    # Turn 1 cards still present
    network.card_by_name("Research Agent")

    # Turn 2 cards added
    network.card_by_name("Code Expert")
    network.card_by_name("Creative Writer")
