"""Deletion must stop real delegated shell work before removing its records."""

import json
import time
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import bash, call_tool, say, spawn
from tests.e2e._runtime import agent_profile
from tests.e2e.pages import ChatView, RoutinesView


@pytest.mark.parametrize("target", ["routine", "run"])
def test_delete_running_work_stops_processes_and_prevents_late_side_effects(page: Page, target: str):
    nonce = uuid4().hex
    description = f"Delete running routine {nonce}"
    gate = f"/home/omnideck/e2e-delete-{nonce}"
    routine_id = None
    try:
        with agent_profile() as profile:
            tasks = []
            for name in ("one", "two"):
                # The shell and its background child stay alive until released.
                # Deletion must kill both before the child can write its effect.
                command = (
                    f"mkdir -p {gate}; ( "
                    f"for attempt in {{1..600}}; do test -e {gate}/release && break; sleep .05; done; "
                    f"test -e {gate}/release && printf late > {gate}/{name}-effect "
                    f") & child=$!; printf '%s %s' $$ $child > {gate}/{name}-ready; wait $child"
                )
                tasks.append({
                    "key": name, "description": name,
                    "instruction": spawn(bash(command), profile=profile["id"], name=name.upper()) + say("finished"),
                    "agent_profile": profile["id"], "depends_on": [],
                })
            ChatView(page).goto().new_conversation().send(call_tool("commit_routine", draft={
                "description": description, "cron": "0 0 1 1 *", "timezone": "UTC", "tasks": tasks,
            }) + say("created")).wait_streaming()
            matches = [r for r in page.request.get("/api/routines").json()["routines"] if r["description"] == description]
            assert len(matches) == 1
            routine_id = matches[0]["id"]
            routines = RoutinesView(page).goto()
            routines.select_by_name(description)
            routines.run_now_button().click()

            deadline = time.monotonic() + 20
            while True:
                ready = json.loads(container_exec(
                    f"import json; from pathlib import Path; p = Path({gate!r}); "
                    "print(json.dumps([f.read_text() for f in p.glob('*-ready')]))"
                ))
                if len(ready) == 2:
                    break
                assert time.monotonic() < deadline, "Both delegated shell tools did not start"
                page.wait_for_timeout(100)
            pids = [int(pid) for entry in ready for pid in entry.split()]
            detail = page.request.get(f"/api/routines/{routine_id}").json()
            assert len(detail["runs"]) == 1
            run = detail["runs"][0]
            assert run["status"] == "running"
            conversations = [result["conversation_id"] for result in run["task_results"]]
            assert len(conversations) == 2 and all(conversations)
            assert all(result["status"] == "running" for result in run["task_results"])

            path = f"/api/routines/{routine_id}"
            if target == "run":
                path += f"/runs/{run['id']}"
            with page.expect_response(
                lambda response: response.request.method == "DELETE" and response.url.endswith(path),
            ) as deleted:
                if target == "routine":
                    routines.delete_button().click()
                    routines.confirm_button().click()
                else:
                    title = page.get_by_text("Run #1", exact=True)
                    expect(title).to_be_visible(timeout=10_000)
                    header = title.locator("xpath=../..")
                    header.get_by_title("Delete run").click()
                    header.get_by_title("Click again to confirm").click()
            assert deleted.value.status == 200

            # A successful delete response means work is gone, not just its row.
            assert page.request.get("/api/runner/status").json()["active_tasks"] == 0
            running = json.loads(container_exec(
                "import json; from pathlib import Path; "
                f"pids = {pids!r}; "
                "print(json.dumps([pid for pid in pids if Path(f'/proc/{pid}/stat').exists() "
                "and Path(f'/proc/{pid}/stat').read_text().split()[2] != 'Z']))"
            ))
            assert running == [], f"Deleted work still has live processes: {running}"
            container_exec(f"from pathlib import Path; (Path({gate!r}) / 'release').touch()")
            effects = json.loads(container_exec(
                f"import json; from pathlib import Path; print(json.dumps([str(p) for p in Path({gate!r}).glob('*-effect')]))"
            ))
            assert effects == []
            remaining_events = json.loads(container_exec(
                "import json; from conversations import load_events_jsonl; "
                f"print(json.dumps([load_events_jsonl(cid) for cid in {conversations!r}]))"
            ))
            assert remaining_events == [[], []]
            remaining_directories = json.loads(container_exec(
                "import json; from conversations._store import _get_conversations_dir; "
                f"print(json.dumps([cid for cid in {conversations!r} "
                "if (_get_conversations_dir() / cid).exists() "
                "or (_get_conversations_dir() / '_archived' / cid).exists()]))"
            ))
            assert remaining_directories == []
            if target == "routine":
                assert page.request.get(f"/api/routines/{routine_id}").status == 404
                expect(page.get_by_test_id("routines-list").get_by_text(description, exact=True)).to_be_hidden()
            else:
                assert page.request.get(f"/api/routines/{routine_id}").json()["runs"] == []
                expect(page.get_by_text("Run #1", exact=True)).to_be_hidden()
    finally:
        if routine_id is not None:
            page.request.delete(f"/api/routines/{routine_id}", fail_on_status_code=False)
        container_exec(f"import shutil; shutil.rmtree({gate!r}, ignore_errors=True)")
