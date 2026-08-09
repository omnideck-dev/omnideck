from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("webdriver_client.py")
SPEC = importlib.util.spec_from_file_location("desktop_webdriver_client", MODULE_PATH)
assert SPEC and SPEC.loader
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class FakeDriver:
    def screenshot(self, _destination: Path) -> None:
        raise AssertionError("WebDriver screenshots must stay opt-in")


class BridgeDriver(FakeDriver):
    def execute(self, _script: str) -> dict[str, object]:
        return {
            "frozen": True,
            "keys": CLIENT.EXPECTED_UPDATE_BRIDGE,
        }


class MultiWindowDriver(FakeDriver):
    def __init__(self) -> None:
        self.current = "hosted"
        self.switched: list[str] = []

    def handles(self) -> list[str]:
        return ["hosted", "setup"]

    def switch_window(self, handle: str) -> None:
        self.current = handle
        self.switched.append(handle)

    def execute(self, _script: str) -> dict[str, object]:
        if self.current == "hosted":
            return {"url": "tauri://localhost/hosted.html", "title": None, "detail": None}
        return {
            "url": "tauri://localhost/",
            "stage": "welcome",
            "title": {"text": "Welcome to omnideck", "hidden": False},
            "detail": {
                "text": "A one-time setup will prepare everything omnideck needs on this computer.",
                "hidden": False,
            },
        }


class WebDriverClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.desktop_root = Path(__file__).resolve().parents[2]
        self.parity = self.desktop_root / "src-tauri" / "setup-parity.json"
        self.mockup_parity = (
            self.desktop_root
            / "tests"
            / "fixtures"
            / "electron-setup"
            / "setup-parity.json"
        )
        self.mockup_html = (
            self.desktop_root
            / "tests"
            / "fixtures"
            / "electron-setup"
            / "index.html"
        )

    def test_frozen_mockup_supplies_parity_and_initial_copy(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        self.assertEqual(initial, ("Starting omnideck", "Checking your environment…"))
        self.assertEqual(parity["setupCopy"]["welcome"]["title"], "Welcome to omnideck")

    def test_parity_drift_fails_before_a_driver_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.json"
            value = json.loads(self.mockup_parity.read_text(encoding="utf-8"))
            value["setupCopy"]["welcome"]["title"] = "Changed"
            changed.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "frozen UX mockup"):
                CLIENT.load_contract(self.parity, changed, self.mockup_html)

    def test_live_copy_record_uses_semantic_markers_without_driver_screenshot(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journey = CLIENT.Journey(
                FakeDriver(), parity, root / "evidence", root / "markers", 5, False, initial
            )
            journey.evidence.mkdir()
            journey.markers.mkdir()
            state = {
                "stage": "welcome",
                "title": {"text": "Welcome to omnideck", "hidden": False},
                "detail": {
                    "text": "A one-time setup will prepare everything omnideck needs on this computer.",
                    "hidden": False,
                },
                "activity": {"text": "", "hidden": True},
            }
            self.assertEqual(journey.record(state), "setup:welcome")
            self.assertTrue((root / "evidence" / "states.json").is_file())
            self.assertTrue(
                (root / "markers" / "state-01-setup-welcome").is_file()
            )

    def test_uncontracted_visible_wording_fails(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journey = CLIENT.Journey(
                FakeDriver(), parity, root, root, 5, False, initial
            )
            with self.assertRaisesRegex(AssertionError, "Uncontracted visible setup copy"):
                journey.validate_copy(
                    {
                        "stage": "welcome",
                        "title": {"text": "Hello"},
                        "detail": {"text": "Changed"},
                    }
                )

    def test_live_state_selects_copy_bearing_window(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        with tempfile.TemporaryDirectory() as directory:
            driver = MultiWindowDriver()
            journey = CLIENT.Journey(
                driver, parity, Path(directory), Path(directory), 5, False, initial
            )
            state = journey.live_state()
            self.assertEqual(CLIENT.text_of(state, "title"), "Welcome to omnideck")
            self.assertEqual(driver.switched, ["hosted", "setup"])
            self.assertEqual(journey.setup_handle, "setup")

            driver.switched.clear()
            journey.live_state()
            self.assertEqual(driver.switched, ["setup"])

    def test_update_bridge_contract_is_recorded(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            markers = root / "markers"
            evidence.mkdir()
            markers.mkdir()
            journey = CLIENT.Journey(
                BridgeDriver(), parity, evidence, markers, 5, False, initial
            )

            journey.assert_update_bridge()

            self.assertEqual(
                json.loads((evidence / "update-bridge.json").read_text()),
                {"frozen": True, "keys": CLIENT.EXPECTED_UPDATE_BRIDGE},
            )
            self.assertTrue((markers / "update-bridge").is_file())


if __name__ == "__main__":
    unittest.main()
