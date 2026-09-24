from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).with_name("host_boundary_client.py")
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("desktop_host_boundary_client", MODULE_PATH)
assert SPEC and SPEC.loader
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class HostBoundaryClientTests(unittest.TestCase):
    def test_pack_filename_matches_server_contract(self) -> None:
        self.assertEqual(
            CLIENT.pack_filename("Desktop Host Boundary de2e-123"),
            "Desktop-Host-Boundary-de2e-123.agent.omnideck.json",
        )
        self.assertEqual(CLIENT.pack_filename(". /"), "pack.agent.omnideck.json")

    def test_pack_filename_caps_the_server_owned_stem(self) -> None:
        filename = CLIENT.pack_filename("a" * 100)
        self.assertEqual(filename, f"{'a' * 64}.agent.omnideck.json")

    def test_imported_profile_name_accepts_the_additive_collision_suffix(self) -> None:
        source = "Desktop Host Boundary"
        self.assertTrue(CLIENT.is_imported_profile_name(source, source))
        self.assertTrue(CLIENT.is_imported_profile_name(f"{source} (imported)", source))
        self.assertTrue(CLIENT.is_imported_profile_name(f"{source} (imported 2)", source))
        self.assertFalse(CLIENT.is_imported_profile_name("Different", source))

    def test_open_agents_does_not_toggle_an_already_open_view_back_to_chat(self) -> None:
        class Driver:
            clicked = False

            def execute(self, _script: str) -> bool:
                return True

            def click(self, _selector: str) -> None:
                self.clicked = True

        driver = Driver()
        journey = CLIENT.HostBoundaryJourney(driver, Path(), 1)

        journey.open_agents()

        self.assertFalse(driver.clicked)

    def test_zoom_layout_accepts_an_anchored_menu_without_overflow(self) -> None:
        snapshot = {
            "cssZoom": "",
            "viewport": {
                "overflow": {"documentX": 0, "documentY": 0, "bodyX": 0, "bodyY": 0},
            },
            "menu": {
                "anchorError": {"x": 0.25, "y": 0.5},
                "insideViewport": True,
            },
            "frames": [
                {"insideViewport": True, "viewportWidthError": 1},
            ],
        }

        self.assertIs(CLIENT.assert_zoom_layout(snapshot, 0.8), snapshot)

    def test_zoom_layout_rejects_the_css_zoom_coordinate_failure(self) -> None:
        snapshot = {
            "cssZoom": "0.8",
            "viewport": {"overflow": {"documentX": 512}},
            "menu": {
                "anchorError": {"x": 270, "y": 140},
                "insideViewport": True,
            },
            "frames": [],
        }

        with self.assertRaisesRegex(AssertionError, "CSS zoom remained active"):
            CLIENT.assert_zoom_layout(snapshot, 0.8)

    def test_zoom_layout_requires_an_iframe_viewport_measurement(self) -> None:
        snapshot = {
            "cssZoom": "",
            "viewport": {
                "overflow": {"documentX": 0, "documentY": 0, "bodyX": 0, "bodyY": 0},
            },
            "menu": {
                "anchorError": {"x": 0, "y": 0},
                "insideViewport": True,
            },
            "frames": [],
        }

        with self.assertRaisesRegex(AssertionError, "no iframe viewport measurement"):
            CLIENT.assert_zoom_layout(snapshot, 1.2)

    def test_zoom_layout_rejects_iframe_viewport_desynchronization(self) -> None:
        snapshot = {
            "cssZoom": "",
            "viewport": {
                "overflow": {"documentX": 0, "documentY": 0, "bodyX": 0, "bodyY": 0},
            },
            "menu": {
                "anchorError": {"x": 0, "y": 0},
                "insideViewport": True,
            },
            "frames": [
                {"insideViewport": True, "viewportWidthError": 320},
            ],
        }

        with self.assertRaisesRegex(AssertionError, "desynchronized iframe layouts"):
            CLIENT.assert_zoom_layout(snapshot, 1.2)


if __name__ == "__main__":
    unittest.main()
