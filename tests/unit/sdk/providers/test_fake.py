"""Tests for the deterministic FakeProvider directive protocol."""

import pytest

from sdk.providers._fake import FakeProvider
from sdk.providers._models import ChatResponse


async def _run(provider, messages, tools=None):
    """Collect (content_text, tool_calls) from a chat_stream call."""
    deltas = []
    final = None
    async for chunk in provider.chat_stream(model="m", messages=messages, tools=tools):
        if isinstance(chunk, ChatResponse):
            final = chunk
        else:
            deltas.append(chunk)
    assert final is not None
    streamed = "".join(d.content or "" for d in deltas)
    return final, streamed


def _user(text):
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": text}]


def _named(name):
    """A throwaway callable with a given __name__ (stands in for a loaded tool)."""
    def f():  # pragma: no cover - never called
        ...
    f.__name__ = name
    return f


# Tools available "as if" the coder/browser skills were already loaded.
_CODER = [_named("run_bash_cmd"), _named("write_file"), _named("send_file")]
_BROWSER = [_named("open_url")]


def _tool_result(messages, tool_name, content="ok"):
    """Append an assistant tool-call turn + its result to the history."""
    return [
        *messages,
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        {"role": "tool", "tool_name": tool_name, "tool_call_id": "x", "content": content},
    ]


@pytest.mark.unit
@pytest.mark.asyncio
class TestSay:
    async def test_say_returns_text_no_tools(self):
        final, streamed = await _run(FakeProvider(), _user("<<SAY>>hello there<<END>>"))
        assert final.message.content == "hello there"
        assert final.message.tool_calls is None
        assert streamed == "hello there"

    async def test_multiline_say_preserved(self):
        md = "```python\ndef hello():\n    return 'world'\n```"
        final, _ = await _run(FakeProvider(), _user(f"<<SAY>>{md}<<END>>"))
        assert final.message.content == md

    async def test_no_directive_echoes_prompt(self):
        final, _ = await _run(FakeProvider(), _user("just some text"))
        assert final.message.content == "just some text"


@pytest.mark.unit
@pytest.mark.asyncio
class TestBash:
    async def test_loads_coder_skill_when_bash_unavailable(self):
        """With no coder tools loaded, the fake loads the skill first."""
        final, _ = await _run(FakeProvider(), _user('<<BASH>>echo "hi"<<END>>'))
        call = final.message.tool_calls[0]
        assert call.function.name == "load_skill"
        assert call.function.arguments == {"name": "coder"}

    async def test_emits_bash_once_skill_loaded(self):
        final, _ = await _run(
            FakeProvider(), _user('<<BASH>>echo "hi"<<END>>'), tools=_CODER
        )
        call = final.message.tool_calls[0]
        assert call.function.name == "run_bash_cmd"
        assert call.function.arguments == {"cmd": 'echo "hi"'}
        assert final.done_reason == "tool_calls"

    async def test_after_tool_result_finishes(self):
        msgs = _tool_result(_user('<<BASH>>echo "hi"<<END>>'), "run_bash_cmd")
        final, _ = await _run(FakeProvider(), msgs, tools=_CODER)
        assert final.message.tool_calls is None
        assert final.message.content == "done"

    async def test_load_skill_result_does_not_advance_directive(self):
        """A load_skill result isn't a logical step — bash still comes next."""
        msgs = _tool_result(_user('<<BASH>>echo "hi"<<END>>'), "load_skill")
        final, _ = await _run(FakeProvider(), msgs, tools=_CODER)
        assert final.message.tool_calls[0].function.name == "run_bash_cmd"


@pytest.mark.unit
@pytest.mark.asyncio
class TestWriteThenSend:
    PROMPT = "<<WRITE notes.txt>>hello<<END>><<SEND>>notes.txt<<END>><<SAY>>sent<<END>>"

    async def test_step1_write(self):
        final, _ = await _run(FakeProvider(), _user(self.PROMPT), tools=_CODER)
        call = final.message.tool_calls[0]
        assert call.function.name == "write_file"
        assert call.function.arguments == {"path": "notes.txt", "content": "hello"}

    async def test_step2_send_after_write(self):
        msgs = _tool_result(_user(self.PROMPT), "write_file")
        final, _ = await _run(FakeProvider(), msgs, tools=_CODER)
        call = final.message.tool_calls[0]
        assert call.function.name == "send_file"
        assert call.function.arguments == {"path": "notes.txt"}

    async def test_step3_final_say_after_send(self):
        msgs = _tool_result(_user(self.PROMPT), "write_file")
        msgs = _tool_result(msgs, "send_file")
        final, _ = await _run(FakeProvider(), msgs, tools=_CODER)
        assert final.message.tool_calls is None
        assert final.message.content == "sent"


@pytest.mark.unit
@pytest.mark.asyncio
class TestOpenAndSpawn:
    async def test_open_url(self):
        final, _ = await _run(
            FakeProvider(), _user("<<OPEN>>https://example.com<<END>>"), tools=_BROWSER
        )
        call = final.message.tool_calls[0]
        assert call.function.name == "open_url"
        assert call.function.arguments == {"url": "https://example.com"}

    async def test_open_loads_browser_skill_when_unavailable(self):
        final, _ = await _run(
            FakeProvider(), _user("<<OPEN>>https://example.com<<END>>")
        )
        call = final.message.tool_calls[0]
        assert call.function.name == "load_skill"
        assert call.function.arguments == {"name": "browser"}

    async def test_spawn_passes_nested_protocol_as_instructions(self):
        prompt = (
            "<<SPAWN coder>><<SAY>>be brief<<END>><<ENDSPAWN>><<SAY>>done<<END>>"
        )
        final, _ = await _run(FakeProvider(), _user(prompt))
        call = final.message.tool_calls[0]
        assert call.function.name == "spawn_agent"
        assert call.function.arguments["profile"] == "coder"
        # Body passed through verbatim so the sub-agent runs it.
        assert call.function.arguments["instructions"] == "<<SAY>>be brief<<END>>"

    async def test_spawn_after_completion_returns_final_say(self):
        prompt = (
            "<<SPAWN coder>><<SAY>>hi<<END>><<ENDSPAWN>><<SAY>>done<<END>>"
        )
        msgs = _tool_result(_user(prompt), "spawn_agent")
        final, _ = await _run(FakeProvider(), msgs)
        assert final.message.tool_calls is None
        assert final.message.content == "done"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_models_offline():
    models = await FakeProvider().list_models()
    names = [m.name for m in models]
    assert any("kimi" in n for n in names)
    assert any("qwen" in n for n in names)


@pytest.mark.unit
def test_env_gating_routes_to_fake(monkeypatch):
    import sdk.providers as providers

    monkeypatch.setenv("MOCK_LLM", "1")
    providers.reset_provider()
    try:
        provider = providers.get_provider("ollama")
        assert isinstance(provider, FakeProvider)
    finally:
        providers.reset_provider()
