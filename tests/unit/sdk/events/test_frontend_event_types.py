"""Keep the checked-in frontend event union synchronized with the SDK."""

from scripts.generate_ui_event_types import OUTPUT, generate


def test_frontend_event_types_match_sdk_models() -> None:
    """The generated frontend contract matches the authoritative models."""
    assert OUTPUT.read_text(encoding="utf-8") == generate()
