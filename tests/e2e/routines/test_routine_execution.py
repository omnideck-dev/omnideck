"""E2E coverage for a real background routine run without a real LLM.

The interactive agent creates the routine through the planning tool. The UI
then triggers it, and the real background runner executes its task through the
same FakeProvider used by the rest of the hermetic E2E suite.
"""

from __future__ import annotations

import time
import json

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import call_tool, open_url, say, send_file, spawn, write_file
from tests.e2e.pages import ChatView, RoutinesView


@pytest.mark.parametrize("delegated", [False, True], ids=["task", "nested-children"])
def test_created_routine_runs_in_background_and_persists_output(page: Page, delegated: bool) -> None:
    nonce = time.time_ns()
    description = f"E2E background routine {nonce}"
    task_description = f"Write routine proof {nonce}"
    output_text = f"routine output {nonce}"
    output_path = f"/home/computron/routine-output-{nonce}.txt"
    task_reply = f"Routine {nonce} completed"
    routine_id: str | None = None

    instruction = open_url("about:blank") + write_file(output_path, output_text) + send_file(output_path)
    if delegated:
        instruction = spawn(
            spawn(instruction + say("leaf proof saved"), profile="research_agent", name="LEAF")
            + say("child proof saved"),
            profile="research_agent",
            name="CHILD",
        )
    instruction += say(task_reply)

    # A far-future recurring schedule keeps commit_routine from auto-queuing a
    # one-shot run. The test deliberately exercises the user's Run now action.
    draft = {
        "description": description,
        "cron": "0 0 1 1 *",
        "timezone": "UTC",
        "tasks": [
            {
                "key": "write-proof",
                "description": task_description,
                "instruction": instruction,
                "depends_on": [],
                # Routines inherit Browser access from their configured agent.
                # This task intentionally exercises a Browser call, so use the
                # shipped agent that explicitly has Browser access.
                "agent_profile": "research_agent",
            }
        ],
    }

    try:
        ChatView(page).goto().new_conversation().send(
            call_tool("commit_routine", draft=draft) + say("Routine created")
        ).wait_streaming()

        matches = [
            routine
            for routine in page.request.get("/api/routines").json().get("routines", [])
            if routine["description"] == description
        ]
        assert len(matches) == 1
        routine_id = matches[0]["id"]

        routines = RoutinesView(page).goto()
        routines.select_by_name(description)
        expect(routines.run_now_button()).to_be_visible()
        routines.run_now_button().click()

        # The production runner polls every five seconds. Wait on its public API
        # until the real task agent, tool loop, file event, and store update have
        # all reached a terminal state.
        deadline = time.monotonic() + 30
        while True:
            detail = page.request.get(f"/api/routines/{routine_id}").json()
            runs = detail["runs"]
            if len(runs) == 1:
                run_result = runs[0]["task_results"]
                if (
                    runs[0]["status"] == "completed"
                    and len(run_result) == 1
                    and run_result[0]["status"] == "completed"
                    and output_path in run_result[0]["file_outputs"]
                ):
                    break
            if time.monotonic() >= deadline:
                pytest.fail(f"routine run did not complete: {detail}")
            time.sleep(0.25)

        assert len(detail["runs"]) == 1
        run = detail["runs"][0]
        assert run["status"] == "completed"
        assert len(run["task_results"]) == 1
        result = run["task_results"][0]
        assert result["result"] == task_reply
        assert result["file_outputs"] == [output_path]
        assert result["conversation_id"]
        assert result["agent_run_id"].startswith("run_")
        assert result["agent_run_id"] != run["id"]

        # Read the actual execution log after task completion. No seeded events
        # or intercepted response fixtures: the runtime generated this hierarchy.
        events = json.loads(
            container_exec(
                "import json\nfrom conversations import load_events_jsonl\n"
                f"print(json.dumps(load_events_jsonl({result['conversation_id']!r})))\n"
            )
        )
        started = {e["agent_name"]: e for e in events if e["type"] == "agent_started"}
        completed = [e for e in events if e["type"] == "agent_completed"]
        assert len(started) == len(completed) == (3 if delegated else 1)
        assert all(e["status"] == "success" for e in completed)
        output_event = next(e for e in events if e["type"] == "file_output")
        assert output_event["agent_id"] == started["LEAF" if delegated else "TASK_AGENT"]["agent_id"]
        if delegated:
            assert started["CHILD"]["parent_agent_id"] == started["TASK_AGENT"]["agent_id"]
            assert started["LEAF"]["parent_agent_id"] == started["CHILD"]["agent_id"]
            spawns = [e for e in events if e["type"] == "spawn_requested"]
            assert {e["correlation_id"] for e in spawns} == {
                started["CHILD"]["correlation_id"],
                started["LEAF"]["correlation_id"],
            }

        # The terminal task state is written only after TaskExecutor returns,
        # so its routine-owned browser context must already have been released.
        browser_status = page.evaluate(
            """
            conversationId => new Promise((resolve, reject) => {
                const url = new URL('/api/browser/control', window.location.href);
                url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
                url.searchParams.set('conversation_id', conversationId);
                const socket = new WebSocket(url);
                const timeout = setTimeout(() => {
                    socket.close();
                    reject(new Error('browser control did not respond'));
                }, 5000);
                socket.onmessage = event => {
                    clearTimeout(timeout);
                    socket.close();
                    resolve(JSON.parse(event.data));
                };
                socket.onerror = () => {
                    clearTimeout(timeout);
                    reject(new Error('browser control connection failed'));
                };
            })
            """,
            result["conversation_id"],
        )
        assert browser_status == {"type": "error", "reason": "no_active_browser"}

        file_response = page.request.get(output_path)
        assert file_response.ok
        assert file_response.text() == output_text

        # Re-enter the detail to prove the UI renders persisted server state,
        # not optimistic state retained from the trigger click.
        page.get_by_test_id("routine-detail-back").click()
        expect(page.get_by_test_id("routines-list")).to_be_visible()
        routines.select_by_name(description)
        run_title = page.get_by_text("Run #1", exact=True)
        expect(run_title).to_be_visible(timeout=10_000)
        run_header = run_title.locator("xpath=../..")
        expect(run_header).to_contain_text("COMPLETE")
        expect(run_header).to_contain_text("1/1 tasks")

        run_title.click()
        page.get_by_role("button", name="View output").click()
        output_modal = page.get_by_test_id("task-output-modal")
        expect(output_modal).to_be_visible()
        expect(output_modal).to_contain_text(task_description)
        expect(output_modal).to_contain_text(task_reply)
        output_modal.get_by_role("button", name="Close").click()

        delete_run = run_header.get_by_title("Delete run")
        delete_run.click()
        run_header.get_by_title("Click again to confirm").click()
        expect(run_title).to_be_hidden(timeout=10_000)
        assert page.request.get(f"/api/routines/{routine_id}").json()["runs"] == []
    finally:
        if routine_id is not None:
            page.request.delete(f"/api/routines/{routine_id}", fail_on_status_code=False)
        container_exec(f"import pathlib\npathlib.Path({output_path!r}).unlink(missing_ok=True)\n")
