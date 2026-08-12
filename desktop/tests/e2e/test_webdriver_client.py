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


class RestartDriver(FakeDriver):
    def __init__(self) -> None:
        self.clicked: list[str] = []

    def click(self, selector: str) -> None:
        self.clicked.append(selector)

    def execute(self, _script: str) -> dict[str, object]:
        raise CLIENT.WebDriverError("the reboot tore down the WebView")


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


class TransientHostedDriver(FakeDriver):
    def __init__(self) -> None:
        self.handle_attempts = 0

    def handles(self) -> list[str]:
        self.handle_attempts += 1
        if self.handle_attempts == 1:
            raise CLIENT.WebDriverError("temporary native-driver disconnect")
        return ["hosted"]

    def switch_window(self, _handle: str) -> None:
        return

    def execute(self, _script: str) -> dict[str, object]:
        return {
            "url": "http://127.0.0.1:2338/",
            "bodyText": "Welcome to Omnideck",
            "buttonTexts": ["Get Started"],
            "selectorFound": True,
        }


class UnsupportedClickDriver(CLIENT.WebDriver):
    def __init__(self) -> None:
        super().__init__("http://unused.invalid")
        self.session_id = "session"
        self.executed = ""

    def command(self, method: str, suffix: str, payload=None):
        if suffix == "/element":
            return {"element-6066-11e4-a52e-4f735466cecf": "node"}
        if suffix.endswith("/click"):
            raise CLIENT.WebDriverError("unsupported operation")
        raise AssertionError((method, suffix, payload))

    def execute(self, script: str) -> bool:
        self.executed = script
        return True


class SendKeysDriver(CLIENT.WebDriver):
    def __init__(self) -> None:
        super().__init__("http://unused.invalid")
        self.session_id = "session"
        self.sent = None

    def command(self, method: str, suffix: str, payload=None):
        if suffix == "/element":
            return {"element-6066-11e4-a52e-4f735466cecf": "file-input"}
        if suffix == "/element/file-input/value":
            self.sent = (method, payload)
            return None
        raise AssertionError((method, suffix, payload))


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

    def test_port_conflict_copy_and_automatic_recovery_are_locked(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        self.assertEqual(
            CLIENT.PORT_CONFLICT_ACTIVITY, "Choosing another private address…"
        )
        self.assertEqual(
            CLIENT.PORT_CONFLICT_STATUS.format(port=2337),
            "Port 2337 is already in use",
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
            updating = parity["setupCopy"]["updating"]
            state = {
                "stage": "preparing",
                "title": {"text": updating["title"]},
                "detail": {"text": updating["detail"]},
                "activity": {"text": CLIENT.PORT_CONFLICT_ACTIVITY},
                "progressValue": {"text": "Port 2337 is already in use"},
                "primary": {"text": "", "hidden": True},
            }
            journey.wait_for = lambda *_args, **_kwargs: state
            journey.finish_setup = lambda *_args, **_kwargs: "opened"

            self.assertEqual(journey.run_port_conflict(2337, "", ""), "opened")
            self.assertEqual(
                (markers / "port-conflict-recovered").read_text(),
                "Port 2337 is already in use\n",
            )

    def test_hosted_wait_retries_a_transient_handle_disconnect(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            markers = root / "markers"
            evidence.mkdir()
            markers.mkdir()
            driver = TransientHostedDriver()
            journey = CLIENT.Journey(
                driver, parity, evidence, markers, 2, False, initial,
                hosted_action="Get Started",
            )

            value = journey.wait_for_hosted(
                "Welcome to Omnideck", '[data-testid="desktop-layout"]'
            )

            self.assertEqual(value["url"], "http://127.0.0.1:2338/")
            self.assertEqual(driver.handle_attempts, 2)

    def test_click_uses_dom_only_when_native_driver_declares_unsupported(self) -> None:
        driver = UnsupportedClickDriver()

        driver.click("#primary")

        self.assertIn('document.querySelector("#primary")', driver.executed)

    def test_send_keys_uses_the_native_w3c_file_input_command(self) -> None:
        driver = SendKeysDriver()

        driver.send_keys('[type="file"]', "/home/tester/Downloads/profile.json")

        self.assertEqual(driver.sent[0], "POST")
        self.assertEqual(driver.sent[1]["text"], "/home/tester/Downloads/profile.json")
        self.assertEqual(driver.sent[1]["value"], list("/home/tester/Downloads/profile.json"))

    def test_restart_now_wording_and_action_are_locked(self) -> None:
        parity, initial = CLIENT.load_contract(
            self.parity, self.mockup_parity, self.mockup_html
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            driver = RestartDriver()
            journey = CLIENT.Journey(
                driver, parity, root, root, 5, False, initial,
                restart_action="now",
            )
            restart = parity["failureCopy"]["restart"]
            state = {
                "stage": "error",
                "title": {"text": restart["title"]},
                "detail": {"text": restart["detail"]},
                "primary": {"text": restart["primaryLabel"], "hidden": False},
                "secondary": {"text": restart["secondaryLabel"], "hidden": False},
            }
            journey.wait_for = lambda *_args, **_kwargs: state

            self.assertEqual(journey.finish_setup("", ""), "restart-started")
            self.assertEqual(driver.clicked, ["#primary"])
            self.assertTrue((root / "restart-required").is_file())
            self.assertTrue((root / "restart-now-selected").is_file())


if __name__ == "__main__":
    unittest.main()
