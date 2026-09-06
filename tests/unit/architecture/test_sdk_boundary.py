"""Prevent the reusable SDK from depending on application packages."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
APPLICATION_MODULES = {
    p.stem if p.is_file() else p.name
    for p in ROOT.iterdir()
    if (p.is_file() and p.suffix == ".py") or (p.is_dir() and (p / "__init__.py").exists())
} - {"sdk"}


def test_sdk_imports_do_not_cross_into_application_packages():
    violations = []
    for path in (ROOT / "sdk").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                function = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if function in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                    modules = [node.args[0].value]
            for module in modules:
                if module.split(".")[0] in APPLICATION_MODULES:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")
    assert violations == []


def test_sdk_imports_and_executes_with_application_imports_blocked():
    # A fresh interpreter catches indirect imports hidden behind SDK package
    # exports. Its provider is supplied by this consumer, with no app setup.
    code = r"""
import asyncio
import importlib
import importlib.abc
import pkgutil
import sys

blocked = set(sys.argv[1:])
class ApplicationBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise ImportError("SDK attempted application import: " + fullname)
sys.meta_path.insert(0, ApplicationBlocker())

import sdk
for module in pkgutil.walk_packages(sdk.__path__, "sdk."):
    importlib.import_module(module.name)
from sdk.providers import ChatResponse, ChatMessage
from sdk.events import AgentEvent, UserMessagePayload, agent_span, publish_event

class Provider:
    async def chat_stream(self, **kwargs):
        assert kwargs["messages"][-1]["content"] == "input"
        yield ChatResponse(message=ChatMessage(content="standalone output"), done_reason="stop")

async def main():
    history = sdk.ConversationHistory(conversation_id="standalone")
    capabilities = sdk.AgentCapabilities([])
    agent = sdk.Agent(name="STANDALONE", description="", instruction="system", provider="supplied", model="test", options={})
    context = sdk.ExecutionContext(execution_id="root.test.1", conversation_id="standalone", run_id="run", event_sink=history, control=sdk.ExecutionControl())
    async with agent_span(agent.name, agent_capabilities=capabilities, execution=context):
        publish_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="input")))
        result = await sdk.AgentExecutor().execute(agent=agent, capabilities=capabilities, history=history, provider=Provider(), context=context)
    assert result.status == "success" and result.output == "standalone output"
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code, *sorted(APPLICATION_MODULES)], cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_application_imports_use_public_sdk_modules():
    violations = []
    for module in APPLICATION_MODULES - {"tests"}:
        root = ROOT / module
        paths = root.rglob("*.py") if root.is_dir() else [root.with_suffix(".py")]
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                for name in modules:
                    if name.startswith("sdk.") and any(part.startswith("_") for part in name.split(".")[1:]):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert violations == []
