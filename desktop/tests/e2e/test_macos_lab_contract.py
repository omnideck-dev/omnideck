import re
import unittest
from pathlib import Path


E2E_DIR = Path(__file__).resolve().parent


class MacOSLabContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guest = (E2E_DIR / "macos_accessibility_guest.sh").read_text(encoding="utf-8")
        cls.runner = (E2E_DIR / "run-macos-lab.sh").read_text(encoding="utf-8")

    def test_matches_cross_platform_functional_journeys(self):
        expected_steps = (
            "packaged read-only smoke",
            "attended first run",
            "returning user",
            "doctor recovery",
            "interrupted setup resume",
            "candidate update reconciliation",
            "occupied saved port recovery",
            "Custom App restart persistence",
            "native host download",
            "native host upload",
            "native artifact download and toast",
            "native zoom shortcut",
            "native update bridge visible contract",
            "DMG removal preserves user and runtime data",
            "DMG reinstall and packaged sidecar smoke",
        )
        for step in expected_steps:
            with self.subTest(step=step):
                self.assertIn(f"current_step='{step}'", self.guest)

    def test_excludes_only_clean_host_podman_setup(self):
        self.assertIn("runtime-ready", self.runner)
        self.assertIn('"$lab_dir/lab.sh" verify "$target"', self.runner)
        self.assertIn('podman container inspect "$container_name"', self.guest)
        self.assertNotIn("podman machine init", self.guest)
        self.assertNotIn("podman machine start", self.guest)
        self.assertNotIn("install Podman", self.guest)

    def test_success_junit_count_matches_declared_cases(self):
        declared = int(re.search(r'<testsuite[^>]+tests="(\d+)"', self.guest).group(1))
        success_document = self.guest.split("<<'XML'", 1)[1].split("\nXML", 1)[0]
        self.assertEqual(declared, success_document.count("<testcase "))

    def test_native_app_launch_retries_until_a_window_is_accessible(self):
        self.assertIn("for attempt in 1 2 3", self.guest)
        self.assertIn('wait-windows "$application" 1 30', self.guest)
        self.assertIn('wait-text "$application" "$expected_text" "$timeout"', self.guest)
        self.assertIn("launch_application first-run 'Welcome to omnideck' 60", self.guest)


if __name__ == "__main__":
    unittest.main()
