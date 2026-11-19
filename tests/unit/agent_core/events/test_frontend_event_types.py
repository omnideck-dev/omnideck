"""Keep the checked-in frontend types synchronized with the backend models."""

from scripts.generate_ui_event_types import ACTIVITY_OUTPUT, OUTPUT, generate, generate_activity


def test_frontend_event_types_match_sdk_models() -> None:
    """The generated frontend contract matches the authoritative models."""
    assert OUTPUT.read_text(encoding="utf-8") == generate()


def test_activity_message_types_are_current() -> None:
    assert ACTIVITY_OUTPUT.read_text(encoding="utf-8") == generate_activity()
