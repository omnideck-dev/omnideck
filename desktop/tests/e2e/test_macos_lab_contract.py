import json
import re
import subprocess
import sys
import tempfile
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

    def test_native_download_brokers_only_the_expected_macos_consent(self):
        self.assertIn(
            'downloads_permission_helper="$HOME/.local/libexec/omnideck-lab/allow-downloads.sh"',
            self.guest,
        )
        download = self.guest.split("current_step='native host download'", 1)[1]
        download = download.split("current_step='native host upload'", 1)[0]
        helper = download.index("\"$downloads_permission_helper\" 'Omnideck Lab' 5")
        confirm = download.index('click-in "$application" "Export “$fixture_name”" \'Export\' 30')
        toast = download.index("wait-text \"$application\" 'Download complete' 10")
        capture = download.index("capture host-download-toast")
        finish = download.index("finish_downloads_permission")
        self.assertLess(helper, confirm)
        self.assertLess(confirm, toast)
        self.assertLess(toast, capture)
        self.assertLess(capture, finish)

    def test_failed_launch_keeps_window_evidence_before_stopping(self):
        launch = self.guest.split("launch_application() {", 1)[1]
        launch = launch.split("\ndump_accessibility()", 1)[0]
        dump = launch.index('dump_accessibility "${attempt_label}-failure"')
        capture = launch.index('capture "${attempt_label}-failure"')
        stop = launch.index("stop_application", dump)
        self.assertLess(dump, capture)
        self.assertLess(capture, stop)

    def test_artifact_download_isolates_named_preview_before_click(self):
        download = self.guest.split("current_step='native artifact download and toast'", 1)[1]
        download = download.split("current_step='native update bridge visible contract'", 1)[0]
        menu = download.index('"Actions for $artifact_filename tab"')
        fullscreen = download.index("click-in \"$application\" 'Tab actions' 'Enter full screen'")
        ready = download.index("wait-text \"$application\" 'Exit full screen'")
        validate = download.index('python3 - "$result_dir/accessibility/artifact-download-target.json"')
        click = download.index("click \"$application\" 'Download file'")
        self.assertLess(menu, fullscreen)
        self.assertLess(fullscreen, ready)
        self.assertLess(ready, validate)
        self.assertLess(validate, click)

    def test_artifact_download_rejects_missing_or_ambiguous_targets(self):
        # Execute the guest's guard against representative native AX records.
        guard = self.guest.split('python3 - "$result_dir/accessibility/artifact-download-target.json"', 1)[1]
        guard = guard.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
        title = {"role": "AXStaticText", "value": "artifact.txt"}
        download = {"role": "AXButton", "description": "Download file"}
        cases = (
            ([title, download], True),
            ([title, download, download], False),
            ([title], False),
            ([{"role": "AXStaticText", "value": "welcome_dashboard.html"}, download], False),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            for records, expected in cases:
                with self.subTest(records=records):
                    path.write_text(json.dumps(records), encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, "-", str(path), "artifact.txt"],
                        input=guard,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
