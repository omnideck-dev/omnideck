"""Seed a welcome conversation on first setup completion.

Creates a pre-built conversation that shows a brand-new user what Omnideck
can do — browse the web, run code, generate an interactive app in the live
preview, delegate to a sub-agent, and drive a browser — so a fresh install
has something friendly and interactive waiting instead of an empty sidebar.

The conversation is a simulated exchange around one ask: "show me what you
can do." A sub-agent writes a getting-started checklist to a file, the agent
generates a "Welcome to Omnideck" capabilities page with a script (the page
loads that checklist file live), and finishes by inviting the user to
continue (browsing, integrations, goals, and memory are offered as next
steps). The page is opened in the preview panel via saved preview state.

The events are built through the real ``AgentEvent`` payload models and
``to_flat_dict`` so the on-disk shape matches a genuine turn exactly
(root events at depth 0, the sub-agent's events at depth 1).

First-run only: this is run once by a data migration, which only seeds when
setup is still incomplete (a fresh install), before the UI lists
conversations — so the conversation shows in the sidebar without a refresh.
Because migrations run exactly once and are never re-applied, existing
installs never get it on upgrade, and a user who deletes it never gets it
back.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from artifacts import record_artifact
from config import load_config
from conversations import _store as _conv_store
from conversations import (
    save_conversation_pinned,
    save_conversation_profile,
    save_conversation_title,
    save_preview_state,
)
from sdk.events._models import (
    AgentCompletedPayload,
    AgentEvent,
    AgentEventPayload,
    AgentStartedPayload,
    FileOutputPayload,
    IterationPayload,
    IterationToolCall,
    SpawnRequestedPayload,
    ToolResultPayload,
    UserMessagePayload,
)
from settings import load_settings

logger = logging.getLogger(__name__)

WELCOME_CONVERSATION_ID = "welcome-to-omnideck"
WELCOME_TITLE = "Welcome to Omnideck 👋"

# The root "Omnideck" agent and the sub-agent it spawns. The turn counter is
# 0 on purpose: the live scheme mints root ids as ``root.<profile>.<n>`` with
# n starting at 1 (itertools.count(1)), so a seeded ``.0`` can never collide
# with a real turn's root id. Without this, the first live turn after a fresh
# start (n=1, default profile "omnideck" -> ``root.omnideck.1``) would reuse
# the seeded root id, clobber the seeded node, and empty the network view when
# the user continues the conversation.
_ROOT_AGENT_ID = "root.omnideck.0"
_ROOT_AGENT_NAME = "Omnideck"
_SUBAGENT_ID = "root.omnideck.0.concierge.1"
_SUBAGENT_NAME = "CONCIERGE"
_SUBAGENT_PROFILE = "Research Agent"

# Artifact filenames written into the virtual computer home directory.
_PAGE_FILENAME = "welcome_dashboard.html"
_CHECKLIST_FILENAME = "checklist.json"
_SCRIPT_FILENAME = "build_page.py"

# The artifact templates the seeder copies into the virtual computer.
_ASSET_DIR = Path(__file__).parent / "_welcome_assets"
_PAGE_SRC = _ASSET_DIR / "welcome_dashboard.html"
_CHECKLIST_SRC = _ASSET_DIR / "checklist.json"
_SCRIPT_SRC = _ASSET_DIR / "build_page.py"

# -- Simulated tool inputs/outputs (canned so the transcript reads as real) --

_CHECKLIST_INSTRUCTIONS = (
    "Draft a 6-item getting-started checklist for a brand-new Omnideck user "
    "and save it as checklist.json in the home directory. Keep every item "
    "unchecked for now."
)
_CHECKLIST_WRITE_PREVIEW = (
    '[{"label": "Have me build a webpage or interactive tool", "done": false}, '
    "... 6 items ...]"
)
_CONCIERGE_SUMMARY = (
    "Saved **checklist.json** — six things to try, from building a page to "
    "setting up an autonomous goal. All unchecked and ready."
)

_BUILD_CMD = "python build_page.py"
_BUILD_OUTPUT = (
    "Wrote welcome_dashboard.html — 6 capability cards, checklist wired to checklist.json."
)

# The parent's message right after the sub-agent finishes: it explains the
# checklist arrived as the spawn_agent tool result.
_SPAWN_RECAP = (
    "📬 Got the checklist back from my Concierge — that arrived as the result "
    "of the `spawn_agent` call above, the same way any tool result does. Now "
    "I'll build a page to show off what I can do, and I'll generate it with a "
    "quick script so it stays easy to tweak:"
)

# The closing message: a quick recap plus inviting next steps. Friendly and
# user-facing — it's the first thing a new user reads.
_FINAL_MESSAGE = (
    "## 🎉 Here's what just happened\n\n"
    "| Capability | What I did |\n"
    "|---|---|\n"
    "| **Sub-agents** | A Concierge wrote your getting-started checklist in its own context |\n"
    "| **Code execution** | Wrote and ran a script to generate this page |\n"
    "| **File artifacts** | Made a page, a data file, and a script — the page reads the data file live |\n"
    "| **Live preview** | The checklist on the right is interactive and loaded from `checklist.json` |\n\n"
    "📦 Everything I made is in **Artifacts** (up in the header) — the page, "
    "the checklist file, and the script that built it.\n\n"
    "## 🚀 Your turn!\n\n"
    "Try asking me to:\n\n"
    "- **\"Check off the first item for me\"** — I just built you a webpage, so "
    "I'll tick it in `checklist.json` and you'll watch the checklist update "
    "**live** on the right\n"
    "- **\"Open this page in a browser and test it\"** — I'll drive a real browser and click through it\n"
    "- **\"Connect my Google Calendar\"** — I'll point you to **Settings → Integrations**, then start using it\n"
    "- **\"Every morning, summarize my inbox\"** — I'll set up an autonomous goal that runs on its own\n"
    "- **\"Remember my name is Alex\"** — I'll save it to memory and use it in future chats\n\n"
    "What would you like to try first?"
)


def _virtual_computer_home() -> Path:
    """Return the virtual computer home directory from config."""
    cfg = load_config()
    return Path(cfg.virtual_computer.home_dir)


def _copy_artifacts(home: Path) -> dict[str, Path]:
    """Copy the bundled artifact templates into the virtual computer home.

    Returns a mapping of logical name → on-disk path for the copied files.
    Overwrites if the files already exist (e.g. from a prior seed).
    """
    home.mkdir(parents=True, exist_ok=True)
    sources = {
        "page": (_PAGE_SRC, _PAGE_FILENAME),
        "checklist": (_CHECKLIST_SRC, _CHECKLIST_FILENAME),
        "script": (_SCRIPT_SRC, _SCRIPT_FILENAME),
    }
    targets: dict[str, Path] = {}
    for key, (src, name) in sources.items():
        dst = home / name
        dst.write_bytes(src.read_bytes())
        targets[key] = dst
        logger.info("Seeded welcome artifact %s -> %s", src.name, dst)
    return targets


# A pending event: its payload plus the attribution the flat dict needs.
_Spec = tuple[AgentEventPayload, str, str, str, int]


def _build_events(
    conversation_id: str,
    artifact_paths: dict[str, Path],
) -> list[dict[str, Any]]:
    """Construct the full event log for the welcome conversation.

    The sequence simulates a real turn around "show me what you can do": a
    Concierge sub-agent writes a checklist to a file, the agent generates an
    interactive capabilities page with a script (the page loads the checklist
    file), drives a browser to check off the first item, then invites the
    user to continue. Root events sit at depth 0; the sub-agent's at depth 1.
    """
    page_path = str(artifact_paths["page"])
    checklist_path = str(artifact_paths["checklist"])
    script_path = str(artifact_paths["script"])
    page_size = _PAGE_SRC.stat().st_size
    checklist_size = _CHECKLIST_SRC.stat().st_size

    specs: list[_Spec] = []

    def root(payload: AgentEventPayload, eid: str) -> None:
        specs.append((payload, eid, _ROOT_AGENT_ID, _ROOT_AGENT_NAME, 0))

    def child(payload: AgentEventPayload, eid: str) -> None:
        specs.append((payload, eid, _SUBAGENT_ID, _SUBAGENT_NAME, 1))

    # -- Agent starts; user asks for a tour --------------------------------
    root(AgentStartedPayload(
        type="agent_started", agent_id=_ROOT_AGENT_ID, agent_name=_ROOT_AGENT_NAME,
        parent_agent_id=None, instruction=None, profile_name=_ROOT_AGENT_NAME,
        correlation_id=None,
    ), "evt_welcome_agent_started")
    root(UserMessagePayload(
        type="user_message",
        content="Show me what Omnideck can do! Give me a quick tour of your capabilities.",
    ), "evt_welcome_user_msg")

    # -- Iteration 0: spawn a Concierge to write the checklist -------------
    correlation_id = "corr_welcome_concierge"
    root(IterationPayload(
        type="iteration", iteration_index=0,
        thinking=(
            "Delegate the checklist to a sub-agent so it runs in its own "
            "context, then build a page to show everything off."
        ),
        content=(
            "Happy to — let me **show** you, not just tell you. I'll have a "
            "specialist draft your getting-started checklist in its own context "
            "while I build a page to show everything off:"
        ),
        tool_calls=[IterationToolCall(
            id="call_welcome_spawn", name="spawn_agent",
            arguments={
                "profile": "research_agent",
                "agent_name": _SUBAGENT_NAME,
                "instructions": _CHECKLIST_INSTRUCTIONS,
            },
        )],
    ), "evt_welcome_iter_0")
    root(SpawnRequestedPayload(
        type="spawn_requested", correlation_id=correlation_id,
    ), "evt_welcome_spawn_requested")

    # -- Sub-agent writes the checklist file (depth 1) ---------------------
    child(AgentStartedPayload(
        type="agent_started", agent_id=_SUBAGENT_ID, agent_name=_SUBAGENT_NAME,
        parent_agent_id=_ROOT_AGENT_ID, instruction=_CHECKLIST_INSTRUCTIONS,
        profile_name=_SUBAGENT_PROFILE, correlation_id=correlation_id,
    ), "evt_welcome_sub_started")
    child(UserMessagePayload(
        type="user_message", content=_CHECKLIST_INSTRUCTIONS,
    ), "evt_welcome_sub_user_msg")
    child(IterationPayload(
        type="iteration", iteration_index=0,
        thinking="Draft six good starter actions and save them as checklist.json.",
        content="Putting together six starter actions and saving them to a file:",
        tool_calls=[IterationToolCall(
            id="call_concierge_0", name="write_file",
            arguments={"path": checklist_path, "content": _CHECKLIST_WRITE_PREVIEW},
        )],
    ), "evt_welcome_sub_iter_0")
    child(ToolResultPayload(
        type="tool_result", tool_call_id="call_concierge_0", tool_name="write_file",
        content=f"File written: {checklist_path}",
    ), "evt_welcome_sub_tool_result_0")
    child(IterationPayload(
        type="iteration", iteration_index=1,
        thinking="Report the checklist back to the parent.",
        content=_CONCIERGE_SUMMARY,
    ), "evt_welcome_sub_iter_1")
    child(AgentCompletedPayload(
        type="agent_completed", agent_id=_SUBAGENT_ID, agent_name=_SUBAGENT_NAME,
        status="success",
    ), "evt_welcome_sub_completed")

    # -- Iteration 1: write the page generator -----------------------------
    root(ToolResultPayload(
        type="tool_result", tool_call_id="call_welcome_spawn", tool_name="spawn_agent",
        content=f"Concierge finished. {_CONCIERGE_SUMMARY}",
    ), "evt_welcome_tool_result_spawn")
    root(IterationPayload(
        type="iteration", iteration_index=1,
        thinking="Generate the capabilities page with a script; the page will load checklist.json at runtime.",
        content=_SPAWN_RECAP,
        tool_calls=[IterationToolCall(
            id="call_welcome_1", name="write_file",
            arguments={
                "path": script_path,
                "content": "#!/usr/bin/env python3\n# build_page.py — generates welcome_dashboard.html\n...",
            },
        )],
    ), "evt_welcome_iter_1")
    root(ToolResultPayload(
        type="tool_result", tool_call_id="call_welcome_1", tool_name="write_file",
        content=f"File written: {script_path}",
    ), "evt_welcome_tool_result_1")

    # -- Iteration 2: run the generator (code execution) -------------------
    root(IterationPayload(
        type="iteration", iteration_index=2,
        thinking="Run the generator inside the sandbox to produce the page.",
        content=f"Now I'll run it:\n\n```bash\n{_BUILD_CMD}\n```",
        tool_calls=[IterationToolCall(
            id="call_welcome_2", name="run_bash_cmd", arguments={"cmd": _BUILD_CMD},
        )],
    ), "evt_welcome_iter_2")
    root(ToolResultPayload(
        type="tool_result", tool_call_id="call_welcome_2", tool_name="run_bash_cmd",
        content=_BUILD_OUTPUT,
    ), "evt_welcome_tool_result_2")

    # -- Iteration 3: send the page + its data file to the preview ---------
    root(IterationPayload(
        type="iteration", iteration_index=3,
        thinking="Surface the page and the checklist file it reads so the user sees both.",
        content=(
            f"✅ Built cleanly:\n\n```\n{_BUILD_OUTPUT}\n```\n\n"
            "Here it is in your preview — the six things I can do, and at the "
            "bottom a **Getting started checklist that's reading the file the "
            "Concierge just wrote**. It re-reads that file live, so tick items "
            "off yourself — or ask me to and watch them update:"
        ),
        tool_calls=[
            IterationToolCall(id="call_welcome_3a", name="send_file", arguments={"path": page_path}),
            IterationToolCall(id="call_welcome_3b", name="send_file", arguments={"path": checklist_path}),
        ],
    ), "evt_welcome_iter_3")
    root(ToolResultPayload(
        type="tool_result", tool_call_id="call_welcome_3a", tool_name="send_file",
        content=f"File '{_PAGE_FILENAME}' ({page_size} bytes, text/html) sent to the UI.",
    ), "evt_welcome_tool_result_3a")
    root(ToolResultPayload(
        type="tool_result", tool_call_id="call_welcome_3b", tool_name="send_file",
        content=f"File '{_CHECKLIST_FILENAME}' ({checklist_size} bytes, application/json) sent to the UI.",
    ), "evt_welcome_tool_result_3b")
    root(FileOutputPayload(
        type="file_output", filename=_PAGE_FILENAME, content_type="text/html",
        content=None, path=page_path, tool_call_id="call_welcome_3a",
    ), "evt_welcome_file_output_page")
    root(FileOutputPayload(
        type="file_output", filename=_CHECKLIST_FILENAME, content_type="application/json",
        content=None, path=checklist_path, tool_call_id="call_welcome_3b",
    ), "evt_welcome_file_output_checklist")

    # -- Iteration 4: wrap up ----------------------------------------------
    root(IterationPayload(
        type="iteration", iteration_index=4,
        thinking="Recap what was demonstrated and invite the user to continue.",
        content=_FINAL_MESSAGE,
    ), "evt_welcome_iter_4")
    root(AgentCompletedPayload(
        type="agent_completed", agent_id=_ROOT_AGENT_ID, agent_name=_ROOT_AGENT_NAME,
        status="success",
    ), "evt_welcome_agent_completed")

    # Stamp monotonically increasing timestamps and flatten through the real
    # AgentEvent serializer so the on-disk shape matches a genuine turn.
    base = datetime.now(UTC)
    events: list[dict[str, Any]] = []
    for i, (payload, eid, agent_id, agent_name, depth) in enumerate(specs):
        event = AgentEvent(
            payload=payload, id=eid, timestamp=base + timedelta(seconds=i),
            agent_id=agent_id, agent_name=agent_name, depth=depth,
        )
        events.append(event.to_flat_dict(conversation_id))
    return events


def _write_events_jsonl(conversation_id: str, events: list[dict[str, Any]]) -> None:
    """Write the event list as a newline-delimited JSON file."""
    conv_dir = _conv_store._get_conversations_dir() / conversation_id
    conv_dir.mkdir(parents=True, exist_ok=True)
    path = conv_dir / "events.jsonl"
    lines = [json.dumps(e, default=str) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record_artifacts(conversation_id: str, artifact_paths: dict[str, Path]) -> None:
    """Index the generated files into the artifacts hub.

    A live ``send_file`` records the file via an event observer; the seeder
    writes its file_output events straight to disk, so it indexes them here
    explicitly — otherwise the welcome files would never appear in the hub.
    Best-effort: a hub-indexing failure must not abort seeding.
    """
    sent_at = datetime.now(UTC).isoformat()
    files = [
        (artifact_paths["page"], _PAGE_FILENAME, "text/html"),
        (artifact_paths["checklist"], _CHECKLIST_FILENAME, "application/json"),
        (artifact_paths["script"], _SCRIPT_FILENAME, "text/x-python"),
    ]
    for path, filename, content_type in files:
        try:
            record_artifact(
                conversation_id=conversation_id,
                path=str(path),
                filename=filename,
                content_type=content_type,
                agent_name=_ROOT_AGENT_NAME,
                sent_at=sent_at,
            )
        except Exception:
            logger.exception("Failed to index welcome artifact %s", filename)


def seed_welcome_conversation() -> str | None:
    """Create the welcome conversation on a fresh install.

    Copies the artifact templates into the virtual computer home, indexes
    them in the artifacts hub, saves metadata (title, pinned, profile,
    preview state with the page open), and writes the simulated
    events.jsonl. ``events.jsonl`` is written last because it is the marker
    that makes the conversation "exist" (the sidebar and resume key on it),
    so a failure mid-metadata can't leave a half-built conversation showing.

    Returns the conversation id if seeded, or None if it already exists —
    the existence check just avoids clobbering an already-seeded conversation.
    """
    conv_dir = _conv_store._get_conversations_dir() / WELCOME_CONVERSATION_ID
    if (conv_dir / "events.jsonl").exists():
        logger.info("Welcome conversation already exists — skipping seed")
        return None

    home = _virtual_computer_home()
    artifact_paths = _copy_artifacts(home)
    events = _build_events(WELCOME_CONVERSATION_ID, artifact_paths)

    # Use the default agent from settings (set by the setup wizard just
    # before this seed runs) so the profile matches what the user chose.
    default_agent = load_settings().get("default_agent") or "omnideck"
    save_conversation_title(WELCOME_CONVERSATION_ID, WELCOME_TITLE)
    save_conversation_pinned(WELCOME_CONVERSATION_ID, True)
    save_conversation_profile(WELCOME_CONVERSATION_ID, default_agent)
    save_preview_state(WELCOME_CONVERSATION_ID, {
        "open_files": [
            str(artifact_paths["page"]),
            str(artifact_paths["checklist"]),
        ],
        "active_tab": f"file:{artifact_paths['page']}",
        "browser_visible": False,
        "terminal_visible": False,
        "desktop_visible": False,
        "generation_visible": False,
    })
    _record_artifacts(WELCOME_CONVERSATION_ID, artifact_paths)

    # events.jsonl last — the commit point that makes the conversation real.
    _write_events_jsonl(WELCOME_CONVERSATION_ID, events)

    logger.info("Seeded welcome conversation '%s'", WELCOME_CONVERSATION_ID)
    return WELCOME_CONVERSATION_ID


__all__ = ["WELCOME_CONVERSATION_ID", "seed_welcome_conversation"]
