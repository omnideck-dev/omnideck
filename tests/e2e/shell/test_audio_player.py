"""E2E coverage for chat-triggered audio playback."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, call_tool
from tests.e2e.pages import ChatView

_AUDIO_PATH = "/home/computron/e2e-audio.wav"
_CREATE_AUDIO = (
    'python3 -c "import wave; '
    f"w=wave.open('{_AUDIO_PATH}','wb'); "
    "w.setparams((1,2,8000,80000,'NONE','not compressed')); "
    'w.writeframes(bytes(160000)); w.close()"'
)


def test_audio_event_opens_player(page: Page):
    """A real play_audio tool event reaches the application audio player."""
    chat = ChatView(page).goto().new_conversation()

    chat.send(
        bash(_CREATE_AUDIO)
        + call_tool("play_audio", path=_AUDIO_PATH)
    ).wait_streaming()

    player = page.get_by_test_id("audio-player")
    media = page.get_by_test_id("audio-player-media")
    expect(player).to_be_visible()
    expect(player).to_have_attribute("title", "Pause")
    expect(media).to_have_attribute("src", re.compile(r"^data:audio/[^;]+;base64,"))
