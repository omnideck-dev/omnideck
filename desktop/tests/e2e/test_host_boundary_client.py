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


if __name__ == "__main__":
    unittest.main()
